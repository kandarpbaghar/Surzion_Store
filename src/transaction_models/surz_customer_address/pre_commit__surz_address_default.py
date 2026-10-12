# project: Surzion_Store
# object_name: surz_customer_address
# object_type: T
# event: pre_commit
# function_name: surz_address_default
# language: python
# description: Keep exactly one default address per customer and resolve CUSTOMER_ID
# functional_specification:
# Skipped on delete. Re-reads the saved row by ADDRESS_ID (txn_id).
# 1) Blank CUSTOMER_ID is resolved from SURZ_CUSTOMER.REGISTRY_ID (lowest
#    CUSTOMER_ID); left NULL when no customer exists yet (not an error).
# 2) Owner group = same CUSTOMER_ID when known, else same REGISTRY_ID, else
#    just this row.
# 3) Only address in the group -> IS_DEFAULT = 'Y'.
# 4) Otherwise IS_DEFAULT = 'Y' on this row clears 'Y' on every other row of the
#    group (CHG_DATE / CHG_USER refreshed on rows changed); anything other than
#    'Y' is normalised to 'N'.
# 5) A group left with no default promotes the earliest-added other row.
# Returns None; on any failure logs and returns {'error': 'Could not save the address'}.

_FAILURE_TEXT = 'Could not save the address'
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


def run(args):
    try:
        if _text(args.get('action')).lower() == 'delete':
            return None
        header = args.get('header') or {}
        address_id = (_text(_pick(header, 'ADDRESS_ID', 'address_id'))
                      or _text(args.get('txn_id')))
        if not address_id:
            log('surz_address_default: no address id in the payload')
            return {'error': _FAILURE_TEXT}
        tbl = db.t('SURZ_CUSTOMER_ADDRESS')
        row = db.query_one(
            'SELECT ADDRESS_ID, CUSTOMER_ID, REGISTRY_ID, IS_DEFAULT FROM ' + tbl
            + ' WHERE ADDRESS_ID = :a', {'a': address_id})
        if row is None:
            log('surz_address_default: address ' + address_id + ' not found')
            return {'error': _FAILURE_TEXT}

        now_ts = now()
        customer_id = _text(row['CUSTOMER_ID'])
        registry_id = _text(row['REGISTRY_ID'])
        changes = {}

        if not customer_id and registry_id:
            cust = db.query_one(
                'SELECT CUSTOMER_ID FROM ' + db.t('SURZ_CUSTOMER')
                + ' WHERE REGISTRY_ID = :r ORDER BY CUSTOMER_ID',
                {'r': registry_id})
            if cust is not None:
                customer_id = _text(cust['CUSTOMER_ID'])
                changes['CUSTOMER_ID'] = customer_id

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
                'SELECT ADDRESS_ID, IS_DEFAULT FROM ' + tbl + ' WHERE '
                + group_sql + ' AND ADDRESS_ID <> :a '
                'ORDER BY ADD_DATE, ADDRESS_ID',
                {'g': group_val, 'a': address_id}) or []

        wants_default = _text(row['IS_DEFAULT']).upper() == 'Y'
        if not others:
            wants_default = True
        elif wants_default:
            for other in others:
                if _text(other['IS_DEFAULT']).upper() == 'Y':
                    db.update('SURZ_CUSTOMER_ADDRESS', {
                        'IS_DEFAULT': 'N', 'CHG_DATE': now_ts,
                        'CHG_USER': _SYSTEM_USER,
                    }, {'ADDRESS_ID': _text(other['ADDRESS_ID'])})
        else:
            has_default = False
            for other in others:
                if _text(other['IS_DEFAULT']).upper() == 'Y':
                    has_default = True
            if not has_default:
                db.update('SURZ_CUSTOMER_ADDRESS', {
                    'IS_DEFAULT': 'Y', 'CHG_DATE': now_ts,
                    'CHG_USER': _SYSTEM_USER,
                }, {'ADDRESS_ID': _text(others[0]['ADDRESS_ID'])})

        flag = 'Y' if wants_default else 'N'
        if flag != _text(row['IS_DEFAULT']):
            changes['IS_DEFAULT'] = flag
        if changes:
            changes['CHG_DATE'] = now_ts
            changes['CHG_USER'] = _SYSTEM_USER
            db.update('SURZ_CUSTOMER_ADDRESS', changes, {'ADDRESS_ID': address_id})
        return None
    except Exception as exc:
        log('surz_address_default: failed: ' + str(exc))
        return {'error': _FAILURE_TEXT}
