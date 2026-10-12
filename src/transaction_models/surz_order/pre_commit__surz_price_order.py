# project: Surzion_Store
# object_name: surz_order
# object_type: T
# event: pre_commit
# function_name: surz_price_order
# language: python
# description: Price the whole order
# functional_specification:
# Recompute the order's money from its OWN lines and the product master, never
# from the client. UNIT_PRICE **and GST_RATE** are re-read from SURZ_PRODUCT
# and LINE_TOTAL re-derived as round(QTY * UNIT_PRICE, 2); all three are
# written back to the line, so no money input that arrived over the wire
# reaches the total — the TAX RATE included. GST_RATE is editable and
# optional on the line form, so leaving it to the client let a taxable
# instrument be posted at 0% and the GST and the total fall with it: the one
# money input still coming off the wire, in the function whose whole purpose
# is that none of them do. SUBTOTAL = sum(LINE_TOTAL). DISCOUNT_AMT comes
# from SURZ_DISCOUNT
# where CODE = DISCOUNT_CODE: an unknown or inactive code is an ERROR that
# aborts the save, while a real code that simply does not apply (the order date
# falls outside VALID_FROM/VALID_TO, or SUBTOTAL < MIN_ORDER) gives 0 and a
# non-blocking type-'P' prompt naming the reason. A NULL VALID_FROM/VALID_TO
# means no bound on that side; IS_ACTIVE is mandatory with default 'Y', so a
# blank cannot arise and blank is read as active.
# PER-LINE DISCOUNT BEFORE TAX: when the code applies, every line gets
# DISC_PCT = SURZ_DISCOUNT.PERCENT_OFF, DISC_AMT = round(LINE_TOTAL * pct / 100, 2)
# and TAXABLE_VALUE = LINE_TOTAL - DISC_AMT (all written to SURZ_ORDER_LINE;
# with no applicable code DISC_PCT = DISC_AMT = 0 and TAXABLE_VALUE = LINE_TOTAL).
# DISCOUNT_AMT = sum of the line discounts. GST_AMT = sum(round(TAXABLE_VALUE *
# GST_RATE / 100, 2)), GST_RATE
# taken from the PRODUCT MASTER and falling back to the line only when the
# master itself has none — and when neither carries one the line is taxed at
# 0% and says so in a prompt, so an untaxed line is never mistaken for a
# zero-rated one.
# PARTNER CODES: when the code carries SURZ_DISCOUNT.PARTNER_ID the partner
# must be STATUS = 'APPROVED' in SURZ_PARTNER, else the save is refused with
# 'This partner code is not active yet'. SURZ_ORDER.PARTNER_ID / PARTNER_NAME /
# PARTNER_REGISTRY_ID are stamped from that partner and blanked when the code
# is not a partner code (or there is no code).
# SHIPPING_AMT = 0 when
# SUBTOTAL >= 5000 else 250; TOTAL_AMOUNT = SUBTOTAL - DISCOUNT_AMT + GST_AMT
# + SHIPPING_AMT.
# The amounts are written to SURZ_ORDER on the save's own connection (the
# header row already exists by pre_commit time). A save with no lines is
# refused.
#
# PRICE IS HISTORY ONCE THE ORDER LEAVES. Every update re-runs this hook, so
# stamping a courier, a tracking number or the app-payments write-back would
# otherwise re-price a shipped order against TODAY's catalogue — and abort
# the save outright if an instrument had since been withdrawn, which is a
# refusal the person stamping a tracking number can do nothing about. Once
# ORDER_STATUS is past CONFIRMED the hook does nothing at all: what was
# charged is what was charged.
#
# KNOWN AND ACCEPTED: these corrections are made after the rows were written
# and their history stamped, so the record audit trail shows the amounts as
# POSTED, not as corrected. Accepted deliberately — the alternative is to
# re-stamp history from business logic, which would misreport who changed what.

_FREE_SHIPPING_FROM = Decimal('5000')
_SHIPPING_CHARGE = Decimal('250')
_CENT = Decimal('0.01')
_ACTIVE_VALUES = ('Y', 'YES', '1', 'T', 'TRUE')
# ORDER_STATUS values at or beyond which the money is settled history. Taken
# straight from the column's own dropdown (NEW, CONFIRMED, PACKED, SHIPPED,
# DELIVERED, CANCELLED) — everything PAST 'CONFIRMED'.
_PRICE_IS_HISTORY = ('PACKED', 'SHIPPED', 'DELIVERED', 'CANCELLED')
# Prompt identities. A prompt names the column it is ABOUT — a GST problem
# highlighting the discount field sends the operator to the wrong screen.
_DISCOUNT_PROMPT = 'SURZDISC0'
_GST_PROMPT = 'SURZGST0'


def _text(value):
    if value is None:
        return ''
    return str(value).strip()


def _pick(row, *names):
    """A value out of a plain dict (header / row) by any of its spellings."""
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


def _dec(value):
    if value is None or value == '':
        return Decimal('0')
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal('0')


def _money(value):
    """2 dp, HALF-UP — the rounding a printed invoice uses."""
    try:
        return _dec(value).quantize(_CENT, rounding='ROUND_HALF_UP')
    except Exception:
        return Decimal('0')


def _prompt(code, field, message):
    """One non-blocking type-'P' entry, scoped to the column it concerns."""
    return {'code': code, 'field': field, 'type': 'P', 'message': message}


def run(args):
    header = args.get('header') or {}
    order_no = _text(_pick(header, 'ORDER_NO', 'order_no')) or _text(args.get('txn_id'))
    if not order_no:
        return {'error': 'The order number is missing — the order cannot be priced.'}

    # A shipped, delivered or cancelled order is not re-priced. The save that
    # reaches here is a courier, a tracking number or the payment write-back,
    # and neither today's catalogue nor a withdrawn instrument may change
    # what the customer was charged — or refuse the stamp.
    if _text(_pick(header, 'ORDER_STATUS', 'order_status')).upper() in _PRICE_IS_HISTORY:
        return None

    # ── Take the price AND THE TAX RATE back off the CATALOGUE, at once ────
    # One set-based statement rather than a read-modify-write per line: the
    # price, the rate and the line total are never carried through this
    # process in Python, so there is nothing for a posted value to influence,
    # and an order of any size costs one round trip. (UPDATE ... FROM is the Postgres
    # form; this project is a Postgres project — application.db_mode.)
    db.execute(
        'UPDATE ' + db.t('SURZ_ORDER_LINE') + ' AS l '
        'SET UNIT_PRICE = p.UNIT_PRICE, '
        '    GST_RATE = COALESCE(p.GST_RATE, l.GST_RATE), '
        '    LINE_TOTAL = ROUND(COALESCE(l.QTY, 0) * p.UNIT_PRICE, 2) '
        'FROM ' + db.t('SURZ_PRODUCT') + ' AS p '
        'WHERE p.PRODUCT_CODE = l.PRODUCT_CODE AND l.ORDER_NO = :order_no',
        {'order_no': order_no},
    )

    # Now read the corrected lines. The LEFT JOIN is deliberate: a line whose
    # product is NOT in the catalogue was left untouched by the UPDATE above,
    # and pricing it from what the client sent is exactly what this hook
    # exists to prevent — so it is refused instead.
    lines = db.query(
        'SELECT l.LINE_NO, l.PRODUCT_CODE, l.QTY, l.UNIT_PRICE, l.LINE_TOTAL, '
        'l.GST_RATE, p.PRODUCT_CODE AS MASTER_CODE, p.GST_RATE AS MASTER_GST_RATE '
        'FROM ' + db.t('SURZ_ORDER_LINE') + ' l '
        'LEFT JOIN ' + db.t('SURZ_PRODUCT') + ' p ON p.PRODUCT_CODE = l.PRODUCT_CODE '
        'WHERE l.ORDER_NO = :order_no '
        'ORDER BY l.LINE_NO',
        {'order_no': order_no},
    )
    if not lines:
        return {'error': 'An order must have at least one line.'}

    priced = []
    subtotal = Decimal('0')
    untaxed = []
    for line in lines:
        if line['MASTER_CODE'] is None:
            return {'error': 'Instrument ' + (_text(line['PRODUCT_CODE']) or '?')
                    + ' is no longer in the catalogue — remove the line or '
                      'choose another instrument.'}
        amount = _money(line['LINE_TOTAL'])
        # MASTER FIRST. The line's own rate is only consulted where the
        # catalogue has none of its own — otherwise a rate typed into the
        # form would still decide the tax.
        rate = line['MASTER_GST_RATE']
        if rate is None or rate == '':
            rate = line['GST_RATE']
        if rate is None or rate == '':
            # Neither the line nor the master carries a rate. The line is
            # taxed at 0%, but SAYING so is the point: a zero on a GST
            # document has to be a decision somebody made, not a gap.
            untaxed.append(_text(line['LINE_NO']) or '?')
        priced.append((line['LINE_NO'], amount, _dec(rate)))
        subtotal = subtotal + amount
    subtotal = _money(subtotal)

    prompts = []
    pct = Decimal('0')
    partner_id = ''
    partner_name = ''
    partner_registry = ''
    code =_text(_pick(header, 'DISCOUNT_CODE', 'discount_code'))
    if code:
        offer = db.query_one(
            'SELECT CODE, PERCENT_OFF, MIN_ORDER, VALID_FROM, VALID_TO, IS_ACTIVE, '
            'PARTNER_ID '
            'FROM ' + db.t('SURZ_DISCOUNT')
            + ' WHERE UPPER(CODE) = UPPER(:code) ORDER BY CODE',
            {'code': code},
        )
        if offer is None:
            return {'error': 'Discount code ' + code + ' is not a known code.'}
        # Case-insensitive match: carry the code in its stored case from here
        # on, and write that back to the order (see the header update below).
        code = _text(offer['CODE']) or code
        active = _text(offer['IS_ACTIVE']).upper()
        # IS_ACTIVE is mandatory with default 'Y' in the design, so a blank is
        # not a state a discount can be in; blank still reads as active rather
        # than silently refusing a row that predates the rule.
        if active and active not in _ACTIVE_VALUES:
            return {'error': 'Discount code ' + code + ' is no longer active.'}

        # A partner's code works only while the partner is APPROVED, and the
        # order is stamped with that partner (commission / attribution).
        owner = _text(offer['PARTNER_ID'])
        if not owner:
            # Fallback: the code may be linked only from the partner side.
            linked = db.query_one(
                'SELECT PARTNER_ID FROM ' + db.t('SURZ_PARTNER')
                + ' WHERE UPPER(DISCOUNT_CODE) = UPPER(:c) ORDER BY PARTNER_ID',
                {'c': code})
            if linked is not None:
                owner = _text(linked['PARTNER_ID'])
        if owner:
            partner = db.query_one(
                'SELECT PARTNER_ID, PARTNER_NAME, REGISTRY_ID, STATUS FROM '
                + db.t('SURZ_PARTNER') + ' WHERE PARTNER_ID = :p',
                {'p': owner},
            )
            if partner is None or _text(partner['STATUS']).upper() != 'APPROVED':
                return {'error': 'This partner code is not active yet'}
            partner_id = _text(partner['PARTNER_ID'])
            partner_name = _text(partner['PARTNER_NAME'])
            partner_registry = _text(partner['REGISTRY_ID'])

        order_date = to_date(_pick(header, 'ORDER_DATE', 'order_date')) or today()
        valid_from = to_date(offer['VALID_FROM'])
        valid_to = to_date(offer['VALID_TO'])
        min_order = _dec(offer['MIN_ORDER'])
        # An open-ended VALID_FROM/VALID_TO (the column is nullable) means "no
        # bound on that side", not "never valid".
        if valid_from is not None and order_date < valid_from:
            prompts.append(_prompt(_DISCOUNT_PROMPT, 'discount_code',
                                   'Discount ' + code + ' is not valid until '
                                   + valid_from.strftime('%d-%m-%Y') + '.'))
        elif valid_to is not None and order_date > valid_to:
            prompts.append(_prompt(_DISCOUNT_PROMPT, 'discount_code',
                                   'Discount ' + code + ' expired on '
                                   + valid_to.strftime('%d-%m-%Y') + '.'))
        elif subtotal < min_order:
            prompts.append(_prompt(_DISCOUNT_PROMPT, 'discount_code',
                                   'Discount ' + code + ' needs an order of at '
                                   'least ' + str(_money(min_order)) + '.'))
        else:
            pct = _dec(offer['PERCENT_OFF'])
            if pct < 0:
                pct = Decimal('0')
            if pct > 100:
                pct = Decimal('100')

    # PER-LINE discount BEFORE tax: each line is discounted by the code's
    # percentage, and GST is charged on the discounted (taxable) value. The
    # order discount is the sum of the line discounts, so the printed lines
    # always add up to the header.
    gst = Decimal('0')
    discount = Decimal('0')
    for line_no, amount, rate in priced:
        disc_amt = _money(amount * pct / Decimal('100'))
        taxable = amount - disc_amt
        discount = discount + disc_amt
        gst = gst + _money(taxable * rate / Decimal('100'))
        db.update(
            'SURZ_ORDER_LINE',
            {
                'DISC_PCT': str(_money(pct)),
                'DISC_AMT': str(disc_amt),
                'TAXABLE_VALUE': str(_money(taxable)),
            },
            {'ORDER_NO': order_no, 'LINE_NO': line_no},
        )
    discount = _money(discount)
    gst = _money(gst)

    for line_no in untaxed:
        prompts.append(_prompt(
            _GST_PROMPT, 'gst_rate',
            'Line ' + line_no + ' has no GST rate — taxed at 0%.'))

    shipping = Decimal('0') if subtotal >= _FREE_SHIPPING_FROM else _SHIPPING_CHARGE
    total = _money(subtotal - discount + gst + shipping)

    order_changes = {
            # Exact decimal TEXT, not float(): every column here is NUMERIC on
            # Postgres, but the same DbFacade runs on SQLite in the
            # downloadable/offline runtime, where a column has no scale and
            # float(Decimal('6750.30')) persists as 6750.299999999999.
            'SUBTOTAL': str(subtotal),
            'DISCOUNT_AMT': str(discount),
            'GST_AMT': str(gst),
            'SHIPPING_AMT': str(shipping),
            'TOTAL_AMOUNT': str(total),
            # Blank (NULL) when the code is not a partner code / no code.
            'PARTNER_ID': partner_id or None,
            'PARTNER_NAME': partner_name or None,
            'PARTNER_REGISTRY_ID': partner_registry or None,
    }
    if code:
        # Normalise the typed code to the stored CODE (same as discount_check).
        order_changes['DISCOUNT_CODE'] = code
    db.update('SURZ_ORDER', order_changes, {'ORDER_NO': order_no})

    if prompts:
        # Type 'P' — shown to the operator, never blocking. Each carries its
        # OWN code and field, so the client highlights the column the prompt
        # is actually about.
        return {'prompts': prompts}
    return None
