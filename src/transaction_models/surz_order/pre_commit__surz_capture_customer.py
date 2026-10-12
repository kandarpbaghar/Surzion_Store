# project: Surzion_Store
# object_name: surz_order
# object_type: T
# event: pre_commit
# function_name: surz_capture_customer
# language: python
# description: Create or update the SURZ_CUSTOMER for this order and save the delivery address
# functional_specification:
# Runs FIRST in the pre_commit chain (before surz_reserve_stock and
# surz_price_order). Re-reads the order header by ORDER_NO / txn_id and trims
# REGISTRY_ID, CUSTOMER_NAME, EMAIL, PHONE, SHIP_ADDRESS. EMAIL, PHONE and
# REGISTRY_ID all blank -> error 'Please give an email or phone number'.
# A non-blank CUSTOMER_ID that exists in SURZ_CUSTOMER (admin picked it) is
# used as is (no match / create) but the update and address steps still run.
# MATCH, first hit wins: REGISTRY_ID; lower(trim(EMAIL)); PHONE digits (last 10
# digits when both sides have >= 10, else the whole digit string; only when the
# order phone has >= 7 digits). Several hits -> lowest CUSTOMER_ID. CREATE when
# none match (max numeric id + 1, INSERT ... ON CONFLICT DO NOTHING with retry).
# UPDATE when found: name / email / phone / ship address only where the order
# value is non-blank and differs; REGISTRY_ID only when the stored one is blank.
# Then SURZ_ORDER.CUSTOMER_ID is set. ADDRESS UPSERT: a non-blank SHIP_ADDRESS
# not already on file (normalised: lower-case, no commas, collapsed spaces) is
# inserted into SURZ_CUSTOMER_ADDRESS as 'Delivery' (default when it is the
# customer's first address). Returns None; any failure -> generic error.

_FAILURE_TEXT = 'Could not register your details. Please try again.'
_NO_CONTACT_TEXT = 'Please give an email or phone number'
_SYSTEM_USER = 'SYSTEM'
_ADDR_PREFIX = 'ADR-'
_ADDR_WIDTH = 5


def _text(value):
    if value is None:
        return ''
    return str(value).strip()


def _pick(row, *names):
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


def _digits(value):
    out = ''
    for ch in _text(value):
        if '0' <= ch <= '9':
            out = out + ch
    return out


def _norm_addr(value):
    return ' '.join(_text(value).lower().replace(',', ' ').split())


def _find_customer(registry_id, email, phone):
    """First matching CUSTOMER_ID (lowest on ties) or ''."""
    tbl = db.t('SURZ_CUSTOMER')
    if registry_id:
        row = db.query_one(
            'SELECT CUSTOMER_ID FROM ' + tbl + ' WHERE REGISTRY_ID = :r '
            'ORDER BY CUSTOMER_ID', {'r': registry_id})
        if row is not None:
            return _text(row['CUSTOMER_ID'])
    if email:
        row = db.query_one(
            'SELECT CUSTOMER_ID FROM ' + tbl + ' WHERE LOWER(TRIM(EMAIL)) = :e '
            'ORDER BY CUSTOMER_ID', {'e': email.lower()})
        if row is not None:
            return _text(row['CUSTOMER_ID'])
    digits = _digits(phone)
    if len(digits) >= 7:
        stored = "regexp_replace(COALESCE(PHONE, ''), '[^0-9]', '', 'g')"
        row = db.query_one(
            'SELECT CUSTOMER_ID FROM ' + tbl + ' WHERE '
            '(LENGTH(' + stored + ') >= 10 AND CAST(:n AS INTEGER) >= 10 '
            'AND RIGHT(' + stored + ', 10) = :last10) '
            'OR ' + stored + ' = :whole '
            'ORDER BY CUSTOMER_ID',
            {'n': len(digits), 'last10': digits[-10:], 'whole': digits})
        if row is not None:
            return _text(row['CUSTOMER_ID'])
    return ''


def _create_customer(name, email, phone, registry_id, ship, now_ts, user):
    tbl = db.t('SURZ_CUSTOMER')
    for attempt in range(5):
        top = db.query_one(
            'SELECT MAX(CAST(CUSTOMER_ID AS BIGINT)) AS M, '
            'MAX(LENGTH(CUSTOMER_ID)) AS W FROM ' + tbl
            + " WHERE CUSTOMER_ID ~ '^[0-9]{1,17}$'")
        last = 0
        width = 1
        if top is not None and top['M'] is not None:
            last = int(top['M'])
            width = int(top['W'] or 1)
        new_id = str(last + 1).zfill(width)
        done = db.execute(
            'INSERT INTO ' + tbl + ' (CUSTOMER_ID, CUSTOMER_NAME, EMAIL, PHONE, '
            'REGISTRY_ID, SHIP_ADDRESS, ADD_DATE, ADD_USER, CHG_DATE, CHG_USER) '
            'VALUES (:id, :name, :email, :phone, :reg, :ship, :now, :usr, :now, :usr) '
            'ON CONFLICT (CUSTOMER_ID) DO NOTHING',
            {'id': new_id, 'name': name[:120], 'email': email[:160] or None,
             'phone': phone[:30] or None, 'reg': registry_id or None,
             'ship': ship[:400] or None, 'now': now_ts, 'usr': user})
        if done and done >= 1:
            return new_id
    return ''


def _update_customer(cust_id, name, email, phone, registry_id, ship, now_ts, user):
    tbl = db.t('SURZ_CUSTOMER')
    stored = db.query_one(
        'SELECT CUSTOMER_NAME, EMAIL, PHONE, REGISTRY_ID, SHIP_ADDRESS FROM '
        + tbl + ' WHERE CUSTOMER_ID = :c', {'c': cust_id})
    if stored is None:
        return
    changes = {}
    wanted = (('CUSTOMER_NAME', name[:120]), ('EMAIL', email[:160]),
              ('PHONE', phone[:30]), ('SHIP_ADDRESS', ship[:400]))
    for col, value in wanted:
        if value and value != _text(stored[col]):
            changes[col] = value
    if registry_id and not _text(stored['REGISTRY_ID']):
        changes['REGISTRY_ID'] = registry_id
    if changes:
        changes['CHG_DATE'] = now_ts
        changes['CHG_USER'] = user
        db.update('SURZ_CUSTOMER', changes, {'CUSTOMER_ID': cust_id})


def _upsert_address(cust_id, registry_id, name, phone, ship, now_ts, user):
    tbl = db.t('SURZ_CUSTOMER_ADDRESS')
    existing = db.query(
        'SELECT ADDRESS_ID, ADDRESS_LINE1 FROM ' + tbl
        + ' WHERE CUSTOMER_ID = :c', {'c': cust_id})
    wanted = _norm_addr(ship)
    for row in existing or []:
        if _norm_addr(row['ADDRESS_LINE1']) == wanted:
            return
    is_default = 'N' if existing else 'Y'
    for attempt in range(5):
        top = db.query_one(
            'SELECT MAX(CAST(SUBSTRING(ADDRESS_ID FROM 5) AS BIGINT)) AS M FROM '
            + tbl + " WHERE ADDRESS_ID ~ '^ADR-[0-9]{1,17}$'")
        last = int(top['M']) if top is not None and top['M'] is not None else 0
        new_id = _ADDR_PREFIX + str(last + 1).zfill(_ADDR_WIDTH)
        done = db.execute(
            'INSERT INTO ' + tbl + ' (ADDRESS_ID, REGISTRY_ID, CUSTOMER_ID, LABEL, '
            'CONTACT_NAME, PHONE, ADDRESS_LINE1, IS_DEFAULT, ADD_DATE, ADD_USER, '
            'CHG_DATE, CHG_USER) VALUES (:id, :reg, :c, :lbl, :name, :phone, '
            ':line1, :dflt, :now, :usr, :now, :usr) '
            'ON CONFLICT (ADDRESS_ID) DO NOTHING',
            {'id': new_id, 'reg': registry_id or None, 'c': cust_id,
             'lbl': 'Delivery', 'name': name[:120] or None,
             'phone': phone[:30] or None, 'line1': ship[:400],
             'dflt': is_default, 'now': now_ts, 'usr': user})
        if done and done >= 1:
            return
    raise Exception('could not allocate an address id')


def run(args):
    try:
        header = args.get('header') or {}
        order_no = (_text(_pick(header, 'ORDER_NO', 'order_no'))
                    or _text(args.get('txn_id')))
        if not order_no:
            log('surz_capture_customer: no order number in the payload')
            return {'error': _FAILURE_TEXT}
        if _text(args.get('action')).lower() == 'delete':
            return None

        order = db.query_one(
            'SELECT CUSTOMER_ID, REGISTRY_ID, CUSTOMER_NAME, EMAIL, PHONE, '
            'SHIP_ADDRESS FROM ' + db.t('SURZ_ORDER') + ' WHERE ORDER_NO = :o',
            {'o': order_no})
        if order is None:
            log('surz_capture_customer: order ' + order_no + ' not found')
            return {'error': _FAILURE_TEXT}

        registry_id = _text(order['REGISTRY_ID'])
        name = _text(order['CUSTOMER_NAME'])
        email = _text(order['EMAIL'])
        phone = _text(order['PHONE'])
        ship = _text(order['SHIP_ADDRESS'])
        if not (email or phone or registry_id):
            return {'error': _NO_CONTACT_TEXT}

        now_ts = now()
        user = _SYSTEM_USER

        cust_id = _text(order['CUSTOMER_ID'])
        if cust_id:
            hit = db.query_one(
                'SELECT CUSTOMER_ID FROM ' + db.t('SURZ_CUSTOMER')
                + ' WHERE CUSTOMER_ID = :c', {'c': cust_id})
            if hit is None:
                cust_id = ''
        if not cust_id:
            cust_id = _find_customer(registry_id, email, phone)
            if not cust_id:
                display = name
                if not display and email:
                    display = email.split('@')[0]
                if not display:
                    display = _digits(phone) or registry_id
                cust_id = _create_customer(display, email, phone, registry_id,
                                           ship, now_ts, user)
                if not cust_id:
                    log('surz_capture_customer: could not allocate a customer id')
                    return {'error': _FAILURE_TEXT}
            else:
                _update_customer(cust_id, name, email, phone, registry_id,
                                 ship, now_ts, user)
        else:
            _update_customer(cust_id, name, email, phone, registry_id,
                             ship, now_ts, user)

        db.update('SURZ_ORDER', {'CUSTOMER_ID': cust_id}, {'ORDER_NO': order_no})

        if ship:
            _upsert_address(cust_id, registry_id, name, phone, ship, now_ts, user)
        return None
    except Exception as exc:
        log('surz_capture_customer: failed: ' + str(exc))
        return {'error': _FAILURE_TEXT}
