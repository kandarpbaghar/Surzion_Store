# project: Surzion_Store
# object_name: surz_order
# object_type: T
# event: pre_commit
# function_name: surz_reserve_stock
# language: python
# description: Reserve stock for the order
# functional_specification:
# Reconcile SURZ_PRODUCT.STOCK_QTY against the order's WHOLE surviving line
# set, in one pass, before the save commits. What each line already holds is
# read back from the SURZ_STOCK_MOVE ledger this function writes (REF_NO = the
# order no, LINE_NO = the line), because the previous QTY is nowhere in the
# payload; only the DIFFERENCE is applied. Running over the whole set — rather
# than per row — is what lets a DELETED line give its stock back: a hold with
# no surviving line is released. Taking stock is a CONDITIONAL UPDATE matching
# only when STOCK_QTY >= the difference; when no row is affected the function
# returns {'error': '<product name> has only <n> left'} and the whole save
# rolls back — where <n> is what THIS line could actually reach, the shelf
# plus what the line is still holding, because raising a line from 3 to 10
# with 5 on the shelf can legitimately take 8. Every movement is booked in
# SURZ_STOCK_MOVE — 'OUT' when stock is taken, 'IN' when a shrunk, re-pointed,
# cancelled or deleted line gives it back — stamped ADD_USER 'SYSTEM' so an
# inventory ledger never carries an unattributable row.
#
# A CANCELLED ORDER WANTS NOTHING. When ORDER_STATUS is 'CANCELLED' the
# wanted set is left empty, so every hold nets negative and comes back
# through the release pass that already exists. Cancelling is THE supported
# way to void an order.
#
# DELETING one is deliberately NOT covered, and cannot be: the engine fires
# no business-logic hook on a header delete, so there is no moment at which
# this function could run and a deleted order's stock would stay debited for
# ever. Delete rights on surz_order are revoked in the Access tab instead.
# Do not read the absence of a delete path as an oversight. Both halves COALESCE STOCK_QTY
# so a product whose stock is NULL can be debited as well as credited. The
# correlation read is served by the designed SURZ_STOCK_MOVE_REF index.

# WHY THIS IS A pre_commit AND NOT A cross_update
# A cross_update fires once per SAVED row, so a line the user DELETED fires
# nothing at all and its stock was never returned — the order shrank and the
# shelf did not grow back. A pre_commit sees the whole surviving line set on
# the save's own connection, so "what is held" and "what is wanted" can be
# compared as SETS, which is the only shape in which a removal is visible.
#
# It also turns a per-row pair of statements into two queries for the whole
# order, and lets every RELEASE be applied before any TAKE — so swapping the
# product between two lines, or moving quantity from one line to another,
# cannot fail for want of stock that is about to be given back.
_OUT = 'OUT'
_IN = 'IN'
_MOVE_PREFIX = 'SM'
_MOVE_WIDTH = 10
# Business logic has no identity in its payload (a BL call carries no user
# token), so a row this function writes is attributed to the system rather
# than left with a NULL actor on an inventory ledger.
_SYSTEM_USER = 'SYSTEM'
# The one ORDER_STATUS that means "release everything". Cancelling is the
# supported way to void an order (a DELETE fires no hook at all).
_CANCELLED = 'CANCELLED'

# Quantities are bound as their exact DECIMAL TEXT, never through float().
# Every target column is NUMERIC here, but the same DbFacade runs on SQLite
# in the downloadable/offline runtime, where a column has no scale and
# float(Decimal('6750.30')) would persist as 6750.299999999999. Arithmetic
# and comparison contexts CAST the parameter, so no dialect has to infer a
# type for an untyped literal.


def _text(value):
    if value is None:
        return ''
    return str(value).strip()


def _pick(row, *names):
    """A value out of a plain dict (the header) by any of its spellings."""
    if not row:
        return None
    for name in names:
        if name in row:
            return row[name]
    lowered = {}
    for key in row.keys():
        if isinstance(key, str):
            lowered[key.lower()] = row[key]
    for name in names:
        if isinstance(name, str) and name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _line_key(value):
    """LINE_NO as a stable string: it arrives as 1, 1.0 or '1' depending on the
    path, and the held-versus-wanted sets have to match on it."""
    raw = _text(value)
    if not raw:
        return ''
    try:
        return str(int(float(raw)))
    except (ValueError, TypeError):
        return raw


def _qty(value):
    """A quantity as a 2-dp Decimal (the column is NUMBER(12,2))."""
    if value is None or value == '':
        return Decimal('0')
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'), rounding='ROUND_HALF_UP')
    except Exception:
        return Decimal('0')


def _fmt_qty(value):
    """Quantity for a message: 12 rather than 12.00, 1.5 stays 1.5."""
    amount = _qty(value)
    whole = amount.quantize(Decimal('1'), rounding='ROUND_DOWN')
    if amount == whole:
        return str(int(whole))
    return str(amount)


def _move_id_base():
    """The next number in the SURZ_STOCK_MOVE series, read ONCE for the run.

    MOVE_ID is the table's key and its declared default is auto_generate(),
    which only runs for rows saved through the stock-move object; a direct
    insert has to mint its own. Minting it the SAME way — a fixed prefix and a
    zero-padded counter — keeps one series, so a movement entered by hand
    afterwards continues these numbers instead of starting a second shape.
    MAX over a fixed-width zero-padded suffix is the numeric maximum, and
    LIKE 'SM%' is a sargable prefix match. Read once and incremented in memory
    because this run writes several rows.

    RACE, ACCEPTED AND DELIBERATE: two saves reading the same MAX mint the same
    number, exactly as the engine's own auto_generate() does. MOVE_ID is the
    primary key, so the loser is refused by the unique index and its whole save
    rolls back — the failure is loud and nothing is corrupted.

    NOT retried on the key violation, and here is why: NO Python business-logic
    path opens a savepoint. _invoke_business_function_in_savepoint dispatches
    Python first and RETURNS on the claim; its begin_nested() calls wrap only
    the NATIVE plpgsql/plsql invocation further down. So a failed INSERT here
    aborts the whole batch transaction, and catching it would leave the rest
    of this function issuing statements on a connection Postgres has already
    given up on — a worse failure than the one being avoided. (The same is
    true of a Python cross_update; the savepoint in that helper's NAME is not
    one Python ever reaches.) A wall-clock candidate was rejected for a
    related reason: an NTP step back repeats a value, and it would also knock
    the model's own auto_generate() series into a different shape by becoming
    its MAX+1 seed."""
    top = db.scalar(
        'SELECT MAX(MOVE_ID) FROM ' + db.t('SURZ_STOCK_MOVE')
        + ' WHERE MOVE_ID LIKE :pattern',
        {'pattern': _MOVE_PREFIX + '%'},
    )
    digits = _text(top)[len(_MOVE_PREFIX):]
    try:
        return int(digits) if digits else 0
    except (ValueError, TypeError):
        return 0


def _book(moves, order_no):
    """Write the movements collected for this run."""
    if not moves:
        return None
    nxt = _move_id_base()
    stamp = datetime.datetime.now()
    for product_code, direction, amount, line_key in moves:
        nxt = nxt + 1
        move_id = _MOVE_PREFIX + str(nxt).rjust(_MOVE_WIDTH, '0')
        if len(move_id) > 20:
            return 'Could not allocate a stock movement number.'
        db.insert('SURZ_STOCK_MOVE', {
            'MOVE_ID': move_id,
            'MOVE_DATE': stamp,
            'PRODUCT_CODE': product_code,
            'DIRECTION': direction,
            'QTY': str(amount),
            'REF_NO': order_no,
            'LINE_NO': int(line_key) if line_key.isdigit() else None,
            'REMARKS': 'Order ' + order_no + ' line ' + line_key,
            'ADD_DATE': stamp,
            'ADD_USER': _SYSTEM_USER,
        })
    return None


def _shortfall_message(product_code, names, already_held):
    """What this LINE could actually have taken, not what is on the shelf.

    The line's own outstanding hold is still out when it grows: a line going
    3 -> 10 with 5 on the shelf can legitimately take 8, and "has only 5
    left" sends the customer away for want of stock that was theirs."""
    row = db.query_one(
        'SELECT PRODUCT_NAME, STOCK_QTY FROM ' + db.t('SURZ_PRODUCT') + ' '
        'WHERE PRODUCT_CODE = :product_code',
        {'product_code': product_code},
    )
    if row is None:
        # No master row at all. This is not a shortage — the instrument has
        # been withdrawn, and "has only 0 left" would send the customer off
        # to wait for stock that is never coming. Because this hook runs
        # BEFORE the pricing one, this is the message the operator actually
        # sees, so it has to be the accurate one.
        return ((names.get(product_code) or product_code)
                + ' is no longer in the catalogue — remove the line or '
                  'choose another instrument.')
    name = _text(row['PRODUCT_NAME']) or names.get(product_code) or product_code
    on_hand = _qty(row['STOCK_QTY'])
    return name + ' has only ' + _fmt_qty(on_hand + already_held) + ' left'


def run(args):
    header = args.get('header') or {}
    order_no = _text(_pick(header, 'ORDER_NO', 'order_no')) or _text(args.get('txn_id'))
    if not order_no:
        return {'error': 'The order number is missing — stock cannot be reserved.'}

    # A CANCELLED order wants nothing. Leaving `wanted` empty while `held`
    # stays populated makes every hold net negative, so the release pass
    # below hands the whole order's stock back with no special case of its
    # own. The status is read off the header the save just wrote, falling
    # back to the row itself when the form did not carry the column.
    status = _text(_pick(header, 'ORDER_STATUS', 'order_status')).upper()
    if not status:
        status = _text(db.scalar(
            'SELECT ORDER_STATUS FROM ' + db.t('SURZ_ORDER') + ' '
            'WHERE ORDER_NO = :order_no',
            {'order_no': order_no},
        )).upper()
    cancelled = status == _CANCELLED

    # WANTED: the lines that survived this save, on the save's own connection.
    lines = [] if cancelled else db.query(
        'SELECT LINE_NO, PRODUCT_CODE, PRODUCT_NAME, QTY FROM '
        + db.t('SURZ_ORDER_LINE') + ' WHERE ORDER_NO = :order_no',
        {'order_no': order_no},
    )
    # HELD: what the ledger says this order is already holding, per line and
    # product. LINE_NO IS NOT NULL fences it to the holds this hook books — a
    # stock movement keyed on the order by hand carries no line.
    holds = db.query(
        'SELECT LINE_NO, PRODUCT_CODE, '
        'SUM(CASE WHEN DIRECTION = :out_dir THEN QTY ELSE -QTY END) AS HELD_QTY '
        'FROM ' + db.t('SURZ_STOCK_MOVE') + ' '
        'WHERE REF_NO = :order_no AND LINE_NO IS NOT NULL '
        'GROUP BY LINE_NO, PRODUCT_CODE',
        {'out_dir': _OUT, 'order_no': order_no},
    )

    # One net movement per (line, product): + take, - release. A line that was
    # deleted contributes only its hold, so it nets negative and is released.
    # `held` is kept apart from the net because a refusal has to report what
    # the LINE could reach, which includes the hold it is still carrying.
    wanted = {}
    held = {}
    names = {}
    for line in lines or []:
        code = _text(line['PRODUCT_CODE'])
        if not code:
            continue
        key = (_line_key(line['LINE_NO']), code)
        wanted[key] = (wanted.get(key) or Decimal('0')) + _qty(line['QTY'])
        names[code] = _text(line['PRODUCT_NAME'])
    for hold in holds or []:
        code = _text(hold['PRODUCT_CODE'])
        if not code:
            continue
        key = (_line_key(hold['LINE_NO']), code)
        held[key] = (held.get(key) or Decimal('0')) + _qty(hold['HELD_QTY'])

    keys = sorted(set(list(wanted.keys()) + list(held.keys())))
    moves = []

    # RELEASES FIRST — so stock about to come back is on the shelf before
    # anything tries to take it.
    for key in keys:
        amount = (wanted.get(key) or Decimal('0')) - (held.get(key) or Decimal('0'))
        if amount >= 0:
            continue
        line_key, code = key
        credited = db.execute(
            'UPDATE ' + db.t('SURZ_PRODUCT') + ' '
            'SET STOCK_QTY = COALESCE(STOCK_QTY, 0) + CAST(:amount AS NUMERIC) '
            'WHERE PRODUCT_CODE = :product_code',
            {'amount': str(-amount), 'product_code': code},
        )
        if credited < 1:
            # The product row is gone. Booking an 'IN' for a shelf that does
            # not exist would record a credit nothing received AND leave the
            # next save's `held` arithmetic reading a hold that was never
            # returned. Leave the hold standing instead.
            continue
        moves.append((code, _IN, -amount, line_key))

    # THEN THE TAKES. The WHERE is the stock check, so two concurrent saves
    # cannot both pass it; nothing updated means there is not enough left.
    # COALESCE on BOTH sides of the pair: without it a product whose STOCK_QTY
    # is NULL could be credited by the release above and never debited here,
    # and would report "has only 0 left" for ever.
    for key in keys:
        amount = (wanted.get(key) or Decimal('0')) - (held.get(key) or Decimal('0'))
        if amount <= 0:
            continue
        line_key, code = key
        affected = db.execute(
            'UPDATE ' + db.t('SURZ_PRODUCT') + ' '
            'SET STOCK_QTY = COALESCE(STOCK_QTY, 0) - CAST(:amount AS NUMERIC) '
            'WHERE PRODUCT_CODE = :product_code '
            'AND COALESCE(STOCK_QTY, 0) >= CAST(:amount AS NUMERIC)',
            {'amount': str(amount), 'product_code': code},
        )
        if affected < 1:
            return {'error': _shortfall_message(
                code, names, held.get(key) or Decimal('0'))}
        moves.append((code, _OUT, amount, line_key))

    failed = _book(moves, order_no)
    if failed:
        return {'error': failed}
    return None
