# project: Surzion_Store
# object_name: surz_partner
# object_type: T
# event: post_commit
# function_name: surz_partner_received
# language: python
# description: Acknowledge a new partner application
# functional_specification:
# Runs after commit; returns immediately unless action is 'add'. Re-reads the
# saved SURZ_PARTNER row and emits 'surz_partner_registered' {partner_id,
# partner_name, org_name, email, phone, handle, platform, profile_url,
# follower_range, audience, admin_emails, review_url}.
# follower_range / audience are optional on the form; a blank one travels as
# 'Not provided' so the admin e-mail never shows an empty label.
# admin_emails: comma-separated e-mails of every non-disabled application user
# holding the 'admin' or 'func-admin' role on this application (tenant
# registry, twasta schema); placeholder addresses (@phone.invalid /
# @persona.invalid) are skipped. When nobody holds those roles - or the lookup
# fails - it falls back to the application owner's address, so the review
# request always reaches someone.
# review_url: the Partners screen on the application's own domain.
# A missing row, missing e-mail or any failure is logged and swallowed: this
# hook never reports a failure.

_EVENT_NAME = 'surz_partner_registered'
_PROJECT = 'Surzion_Store'
_ADMIN_ROLES = ('admin', 'func-admin', 'func_admin', 'funcadmin')
_OWNER_EMAIL = 'twasta.surzion@gmail.com'
_REVIEW_URL = 'https://surzion-backend.platform.twasta.ai/surz_partner'
_NOT_PROVIDED = 'Not provided'


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


def _admin_emails():
    """Comma-separated admin / func-admin e-mails, or the owner's address."""
    found = []
    try:
        rows = db.query(
            'SELECT DISTINCT u.email AS email FROM twasta.twasta_user_roles r '
            'JOIN twasta.twasta_registry_users u ON u.user_id = r.user_id '
            'WHERE r.project = :p AND LOWER(r.role) IN (:r1, :r2, :r3, :r4) '
            "AND (u.status IS NULL OR LOWER(u.status) <> 'disabled')",
            {'p': _PROJECT, 'r1': _ADMIN_ROLES[0], 'r2': _ADMIN_ROLES[1],
             'r3': _ADMIN_ROLES[2], 'r4': _ADMIN_ROLES[3]})
        for row in rows or []:
            email = _text(_pick(row, 'email', 'EMAIL'))
            low = email.lower()
            if ('@' not in email or low.endswith('@phone.invalid')
                    or low.endswith('@persona.invalid')):
                continue
            if low not in [e.lower() for e in found]:
                found.append(email)
    except Exception as exc:
        log('surz_partner_received: admin lookup failed, using owner: ' + str(exc))
    if not found:
        log('surz_partner_received: no admin/func-admin user - notifying the owner')
        return _OWNER_EMAIL
    return ', '.join(found)


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
            'follower_range': _text(row['FOLLOWER_RANGE']) or _NOT_PROVIDED,
            'audience': _text(row['AUDIENCE']) or _NOT_PROVIDED,
            'admin_emails': _admin_emails(),
            'review_url': _REVIEW_URL,
        })
    except Exception as exc:
        log('surz_partner_received: could not announce '
            + (partner_id or '(unknown)') + ': ' + str(exc))
    return None
