# project: Surzion_Store
# object_name: surz_partner
# object_type: T
# event: action
# function_name: surz_partner_reject
# language: python
# description: Reject a partner application
# functional_specification:
# Row action. Admin / func-admin only (role read from the optional `_user`
# object when the runtime supplies it). Re-reads the stored row: PENDING only
# and REJECT_REASON must be non-blank. Sets STATUS = 'REJECTED', clears
# APPROVED_ON / APPROVED_BY, then emits 'surz_partner_rejected'
# {partner_id, partner_name, email, reason}; an emit failure is logged only.
# PARTNER ROLE: when REGISTRY_ID is non-blank, api.revoke_role(REGISTRY_ID,
# 'partner') is called; a failure is logged and never rolls back the rejection.

# A row action's payload carries no caller identity today (`_user` absent), so
# CHG_USER falls back to this until the runtime supplies `_user`.
_SYSTEM_USER = 'SYSTEM'
_EVENT_NAME = 'surz_partner_rejected'
_ADMIN_ROLES = ('admin', 'func-admin', 'func_admin', 'funcadmin')


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
        user = args.get('_user')
        user_id = ''
        if isinstance(user, dict):
            roles = [str(r).strip().lower() for r in (user.get('roles') or [])]
            if user.get('is_admin'):
                roles.append('func-admin')
            if not any(r in _ADMIN_ROLES for r in roles):
                return {'error': 'Only an admin can reject a partner.'}
            user_id = _text(user.get('user_id'))[:10]

        partner_id = _text(_pick(args, 'PARTNER_ID', 'partner_id'))
        if not partner_id:
            return {'error': 'The partner id is missing.'}
        row = db.query_one(
            'SELECT PARTNER_ID, PARTNER_NAME, EMAIL, STATUS, REJECT_REASON, '
            'REGISTRY_ID FROM '
            + db.t('SURZ_PARTNER') + ' WHERE PARTNER_ID = :p', {'p': partner_id})
        if row is None:
            return {'error': 'Partner ' + partner_id + ' was not found.'}
        if _text(row['STATUS']).upper() != 'PENDING':
            return {'error': 'Only a PENDING application can be rejected.'}
        reason = _text(row['REJECT_REASON'])
        if not reason:
            return {'error': 'Enter and save a Reject reason first.'}

        db.update('SURZ_PARTNER', {
            'STATUS': 'REJECTED',
            'APPROVED_ON': None,
            'APPROVED_BY': None,
            'CHG_DATE': now(),
            'CHG_USER': user_id or _SYSTEM_USER,
        }, {'PARTNER_ID': partner_id})

        # PARTNER ROLE: make sure a rejected partner does not hold the role.
        # Best effort: logged on failure, never rolls the rejection back.
        registry_id = _text(row['REGISTRY_ID'])
        if registry_id:
            try:
                revoked = api.revoke_role(registry_id, 'partner')
                log('surz_partner_reject: revoke_role(partner) for ' + partner_id
                    + ' -> ' + str(revoked))
            except Exception as exc:
                log('surz_partner_reject: could not revoke role partner from '
                    + partner_id + ': ' + str(exc))

        email = _text(row['EMAIL'])
        if email:
            try:
                api.emit_event(_EVENT_NAME, {
                    'partner_id': partner_id,
                    'partner_name': _text(row['PARTNER_NAME']),
                    'email': email,
                    'reason': reason,
                })
            except Exception as exc:
                log('surz_partner_reject: could not emit ' + _EVENT_NAME
                    + ' for ' + partner_id + ': ' + str(exc))
        return {'message': 'Application rejected.'}
    except Exception as exc:
        log('surz_partner_reject: failed: ' + str(exc))
        return {'error': 'Could not reject the application: ' + str(exc)}
