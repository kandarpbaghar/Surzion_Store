# project: Surzion_Store
# object_name: surz_product_review
# object_type: T
# event: action
# function_name: surz_review_approve
# language: python
# description: Approve a product review
# functional_specification:
# Row action (payload = clicked row, key REVIEW_ID). Admin / func-admin only
# (role read from the optional `_user` object; when the runtime supplies none
# the object edit right is the gate, as in surz_partner_approve). Re-reads the
# stored row. Only PENDING or REJECTED can be approved. Sets STATUS = 'APPROVED'
# and CHG_DATE / CHG_USER (caller short id, else 'SYSTEM'); MODERATOR_NOTE is
# kept. Returns {'message': 'Review approved.'}; any failure returns an error
# and writes nothing.

_SYSTEM_USER = 'SYSTEM'
_ADMIN_ROLES = ('admin', 'func-admin', 'func_admin', 'funcadmin')
_NOT_APPROVABLE = 'Only a pending or rejected review can be approved.'


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
                return {'error': 'Only an admin can approve a review.'}
            user_id = _text(user.get('user_id'))[:10]

        review_id = _text(_pick(args, 'REVIEW_ID', 'review_id'))
        if not review_id:
            return {'error': 'The review id is missing.'}
        row = db.query_one(
            'SELECT REVIEW_ID, STATUS FROM ' + db.t('SURZ_PRODUCT_REVIEW')
            + ' WHERE REVIEW_ID = :r', {'r': review_id})
        if row is None:
            return {'error': 'Review ' + review_id + ' was not found.'}
        if _text(row['STATUS']).upper() not in ('PENDING', 'REJECTED'):
            return {'error': _NOT_APPROVABLE}

        db.update('SURZ_PRODUCT_REVIEW', {
            'STATUS': 'APPROVED',
            'CHG_DATE': now(),
            'CHG_USER': user_id or _SYSTEM_USER,
        }, {'REVIEW_ID': review_id})
        return {'message': 'Review approved.'}
    except Exception as exc:
        log('surz_review_approve: failed: ' + str(exc))
        return {'error': 'Could not approve the review: ' + str(exc)}
