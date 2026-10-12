# project: Surzion_Store
# object_name: surz_customer_payment_method
# object_type: T
# event: pre_commit
# function_name: surz_payment_method_default
# language: python
# description: Keep exactly one default payment method per customer and clean type-specific fields
# functional_specification:
# Skipped on delete. Re-reads the saved row by METHOD_ID (txn_id).
# 1) Blank CUSTOMER_ID resolved from SURZ_CUSTOMER.REGISTRY_ID (lowest id);
#    NULL when none (not an error).
# 2) Type clean-up: METHOD_TYPE <> 'UPI' -> UPI_ID NULL; <> 'CARD' ->
#    CARD_BRAND and CARD_LAST4 NULL. CARD_LAST4 that is not exactly 4 digits is
#    refused ('Only the last 4 digits of a card may be stored'). A full card
#    number, CVV or expiry is never stored or logged. GATEWAY_TOKEN is never
#    taken from the client: forced NULL on 'add', untouched on edit.
# 3) Owner group = CUSTOMER_ID when known, else REGISTRY_ID, else this row.
#    Sole method -> default 'Y'; 'Y' clears every other row's default; anything
#    else is 'N'; a group left without a default promotes the earliest-added
#    other row.
# Returns None; on failure logs (no payload values) and returns
# {'error': 'Could not save the payment method'}.

_FAILURE_TEXT = 'Could not save the payment method'
_LAST4_TEXT = 'Only the last 4 digits of a card may be stored'
_SYSTEM_USER = 'SYSTEM'


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


def _all_digits(value):
    if not value:
        return False
    for ch in value:
        if not ('0' <= ch <= '9'):
            return False
    return True


def run(args):
    try:
        action = _text(args.get('action')).lower()
        if action == 'delete':
            return None
        header = args.get('header') or {}
        method_id = (_text(_pick(header, 'METHOD_ID', 'method_id'))
                     or _text(args.get('txn_id')))
        if not method_id:
            log('surz_payment_method_default: no method id in the payload')
            return {'error': _FAILURE_TEXT}
        tbl = db.t('SURZ_CUSTOMER_PAYMENT_METHOD')
        row = db.query_one(
            'SELECT METHOD_ID, METHOD_TYPE, CUSTOMER_ID, REGISTRY_ID, UPI_ID, '
            'CARD_BRAND, CARD_LAST4, GATEWAY_TOKEN, IS_DEFAULT FROM ' + tbl
            + ' WHERE METHOD_ID = :m', {'m': method_id})
        if row is None:
            log('surz_payment_method_default: method ' + method_id + ' not found')
            return {'error': _FAILURE_TEXT}

        now_ts = now()
        method_type = _text(row['METHOD_TYPE']).upper()
        customer_id = _text(row['CUSTOMER_ID'])
        registry_id = _text(row['REGISTRY_ID'])
        changes = {}

        # Card hygiene first: refuse before anything is written.
        last4 = _text(row['CARD_LAST4'])
        if method_type == 'CARD' and last4:
            if len(last4) != 4 or not _all_digits(last4):
                return {'error': _LAST4_TEXT}

        if not customer_id and registry_id:
            cust = db.query_one(
                'SELECT CUSTOMER_ID FROM ' + db.t('SURZ_CUSTOMER')
                + ' WHERE REGISTRY_ID = :r ORDER BY CUSTOMER_ID',
                {'r': registry_id})
            if cust is not None:
                customer_id = _text(cust['CUSTOMER_ID'])
                changes['CUSTOMER_ID'] = customer_id

        if method_type != 'UPI' and _text(row['UPI_ID']):
            changes['UPI_ID'] = None
        if method_type != 'CARD':
            if _text(row['CARD_BRAND']):
                changes['CARD_BRAND'] = None
            if last4:
                changes['CARD_LAST4'] = None
        if action == 'add' and _text(row['GATEWAY_TOKEN']):
            changes['GATEWAY_TOKEN'] = None

        if customer_id:
            group_sql = 'CUSTOMER_ID = :g'
            group_val = customer_id
        elif registry_id:
            group_sql = 'REGISTRY_ID = :g'
            group_val = registry_id
        else:
            group_sql = None
            group_val = None

        others = []
        if group_sql:
            others = db.query(
                'SELECT METHOD_ID, IS_DEFAULT FROM ' + tbl + ' WHERE '
                + group_sql + ' AND METHOD_ID <> :m '
                'ORDER BY ADD_DATE, METHOD_ID',
                {'g': group_val, 'm': method_id}) or []

        wants_default = _text(row['IS_DEFAULT']).upper() == 'Y'
        if not others:
            wants_default = True
        elif wants_default:
            for other in others:
                if _text(other['IS_DEFAULT']).upper() == 'Y':
                    db.update('SURZ_CUSTOMER_PAYMENT_METHOD', {
                        'IS_DEFAULT': 'N', 'CHG_DATE': now_ts,
                        'CHG_USER': _SYSTEM_USER,
                    }, {'METHOD_ID': _text(other['METHOD_ID'])})
        else:
            has_default = False
            for other in others:
                if _text(other['IS_DEFAULT']).upper() == 'Y':
                    has_default = True
            if not has_default:
                db.update('SURZ_CUSTOMER_PAYMENT_METHOD', {
                    'IS_DEFAULT': 'Y', 'CHG_DATE': now_ts,
                    'CHG_USER': _SYSTEM_USER,
                }, {'METHOD_ID': _text(others[0]['METHOD_ID'])})

        flag = 'Y' if wants_default else 'N'
        if flag != _text(row['IS_DEFAULT']):
            changes['IS_DEFAULT'] = flag
        if changes:
            changes['CHG_DATE'] = now_ts
            changes['CHG_USER'] = _SYSTEM_USER
            db.update('SURZ_CUSTOMER_PAYMENT_METHOD', changes,
                      {'METHOD_ID': method_id})
        return None
    except Exception as exc:
        log('surz_payment_method_default: failed: ' + str(exc))
        return {'error': _FAILURE_TEXT}
