# project: Surzion_Store
# object_name: surz_partner_apply
# object_type: T
# event: post_commit
# function_name: surz_partner_received
# language: python
# description: Acknowledge a new partner application
# functional_specification:
# Runs after commit; returns immediately unless action is 'add'. Re-reads the
# saved SURZ_PARTNER row and emits 'surz_partner_registered' {partner_id,
# partner_name, org_name, email, phone, handle, platform, profile_url,
# follower_range, audience}. A missing row, missing e-mail or any
# failure is logged and swallowed: this hook never reports a failure.

_EVENT_NAME = 'surz_partner_registered'


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
    partner_id = ''
    try:
        if _text(args.get('action')).lower() != 'add':
            return None
        header = args.get('header') or {}
        partner_id = _text(_pick(header, 'PARTNER_ID', 'partner_id')) or _text(args.get('txn_id'))
        if not partner_id:
            log('surz_partner_received: no partner id in the payload - skipped')
            return None
        row = db.query_one(
            'SELECT PARTNER_ID, PARTNER_NAME, ORG_NAME, EMAIL, PHONE, '
            'HANDLE, PLATFORM, PROFILE_URL, FOLLOWER_RANGE, AUDIENCE FROM '
            + db.t('SURZ_PARTNER') + ' WHERE PARTNER_ID = :p', {'p': partner_id})
        if row is None:
            log('surz_partner_received: partner ' + partner_id + ' not found - skipped')
            return None
        email = _text(row['EMAIL'])
        if not email:
            log('surz_partner_received: partner ' + partner_id + ' has no e-mail - skipped')
            return None
        api.emit_event(_EVENT_NAME, {
            'partner_id': partner_id,
            'partner_name': _text(row['PARTNER_NAME']),
            'org_name': _text(row['ORG_NAME']),
            'email': email,
            'phone': _text(row['PHONE']),
            'handle': _text(row['HANDLE']),
            'platform': _text(row['PLATFORM']),
            'profile_url': _text(row['PROFILE_URL']),
            'follower_range': _text(row['FOLLOWER_RANGE']),
            'audience': _text(row['AUDIENCE']),
        })
    except Exception as exc:
        log('surz_partner_received: could not announce '
            + (partner_id or '(unknown)') + ': ' + str(exc))
    return None
