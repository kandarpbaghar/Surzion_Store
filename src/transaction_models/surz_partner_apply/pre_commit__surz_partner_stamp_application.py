# project: Surzion_Store
# object_name: surz_partner_apply
# object_type: T
# event: pre_commit
# function_name: surz_partner_stamp_application
# language: python
# description: Server-stamp STATUS and APPLIED_ON on a new application
# functional_specification:
# Returns immediately unless action is 'add'. The header row already exists on
# the save connection, so UPDATE SURZ_PARTNER for that PARTNER_ID. A new
# application is ALWAYS forced to STATUS = 'PENDING' (an APPROVED / REJECTED
# arriving from a client on add is never trusted) and APPLIED_ON is set to
# today when it is still NULL. Returns None on success; on an unexpected
# failure logs and returns {'error': 'Could not register the application'}.

_FAILURE_TEXT = 'Could not register the application'


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
        if _text(args.get('action')).lower() != 'add':
            return None
        header = args.get('header') or {}
        partner_id = (_text(_pick(header, 'PARTNER_ID', 'partner_id'))
                      or _text(args.get('txn_id')))
        if not partner_id:
            log('surz_partner_stamp_application: no partner id in the payload')
            return {'error': _FAILURE_TEXT}

        db.execute(
            'UPDATE ' + db.t('SURZ_PARTNER')
            + " SET STATUS = 'PENDING', "
            'APPLIED_ON = COALESCE(APPLIED_ON, :today) '
            'WHERE PARTNER_ID = :p',
            {'today': today(), 'p': partner_id})
        return None
    except Exception as exc:
        log('surz_partner_stamp_application: failed: ' + str(exc))
        return {'error': _FAILURE_TEXT}
