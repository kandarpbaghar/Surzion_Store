# project: Surzion_Store
# object_name: surz_partner
# object_type: T
# event: action
# function_name: surz_partner_approve
# language: python
# description: Approve a partner application and issue the discount code and QR
# functional_specification:
# Row action. Admin / func-admin only (role read from the optional `_user`
# object when the runtime supplies it; otherwise the object edit right is the
# gate). Re-reads the stored row, PENDING only. Needs DISCOUNT_PCT in (0,100]
# or an existing DISCOUNT_CODE. The code and % are taken from the FORM as the
# admin set them (the action posts the stored row overlaid with the screen), so
# they need not be saved first. Blank code -> generates SZP-XXXX-NN and inserts
# it into SURZ_DISCOUNT; a NEW code the admin typed (letters, digits, - and _,
# up to 24, stored upper-case) -> inserted with the given % (required); an
# EXISTING code (matched case-insensitively) -> must already be THIS partner's
# (a store-wide code with no partner is refused, never claimed or re-priced),
# and a % given replaces its PERCENT_OFF. The % is rounded to 2 places; a
# non-number is an error. The action runs in one transaction: any error
# return rolls every write back. Sets STATUS/APPROVED_ON/APPROVED_BY/QR_URL. REGISTRY_ID
# CONTRACT: the application's OWN REGISTRY_ID (row-security stamp) is used
# first; the SURZ_CUSTOMER-by-e-mail match runs ONLY as a fallback when it is
# empty (best effort) and the source used is logged. BACKFILL: SURZ_ORDER rows
# with this PARTNER_ID and an empty PARTNER_REGISTRY_ID are stamped with the
# REGISTRY_ID (best effort, logged, never rolls back). Then emits
# 'surz_partner_approved'. An emit failure is logged and never rolls back the
# approval; WELCOME_QUEUED_ON is stamped only when api.emit_event returned
# {'ok': True} (the event row was enqueued for IOFlow). That confirms the
# HAND-OFF, not delivery of the e-mail.
# PARTNER ROLE: once STATUS is APPROVED and REGISTRY_ID is resolved, the role
# 'partner' is granted with api.grant_role(REGISTRY_ID, 'partner'); blank
# REGISTRY_ID -> logged only; a grant failure is logged, never rolls back.
# ACTING USER: a row action's payload carries NO caller identity (only the form
# values), so `_user` is absent today. ADD_USER / CHG_USER fall back to
# _SYSTEM_USER and APPROVED_BY is left NULL (never a made-up approver) until
# the runtime supplies `_user`; this code uses it as soon as it appears.

# The partner portal the welcome e-mail links to.
_PARTNER_PORTAL_URL = 'https://surzion.platform.twasta.ai/partner-portal'
# Audit stamp used ONLY when the payload does not identify the caller.
_SYSTEM_USER = 'SYSTEM'
_EVENT_NAME = 'surz_partner_approved'
_ADMIN_ROLES = ('admin', 'func-admin', 'func_admin', 'funcadmin')
_QR_BASE = 'https://api.qrserver.com/v1/create-qr-code/?size=300x300&data='
_SAFE = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~'


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


def _dec(value):
    if value is None or value == '':
        return Decimal('0')
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal('0')


def _pct_text(value):
    return str(_dec(value).quantize(Decimal('0.01'), rounding='ROUND_HALF_UP'))


def _encode(value):
    out = ''
    for ch in value:
        if ch in _SAFE:
            out = out + ch
        else:
            for byte in ch.encode('utf-8'):
                out = out + '%' + ('%02X' % byte)
    return out


def _caller(args):
    """(short_id, roles or None). None roles = identity not exposed."""
    user = args.get('_user')
    if isinstance(user, dict):
        roles = [str(r).strip().lower() for r in (user.get('roles') or [])]
        if user.get('is_admin'):
            roles.append('func-admin')
        return _text(user.get('user_id')), roles
    return '', None


def _base_letters(name):
    letters = ''
    for ch in _text(name).upper():
        if 'A' <= ch <= 'Z':
            letters = letters + ch
        if len(letters) == 4:
            break
    return (letters + 'XXXX')[:4]


_CODE_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_'


def _valid_code(code):
    if not code or len(code) > 24:
        return False
    for ch in code:
        if ch not in _CODE_CHARS:
            return False
    return True


def _insert_code(code, pct, partner_id, name, stamp_user, now_ts):
    db.insert('SURZ_DISCOUNT', {
        'CODE': code,
        'DESCR': ('Partner ' + name)[:160],
        'PERCENT_OFF': str(pct),
        'MIN_ORDER': '0',
        'IS_ACTIVE': 'Y',
        'PARTNER_ID': partner_id,
        'PARTNER_NAME': name[:120],
        'USAGE_COUNT': 0,
        'ADD_DATE': now_ts,
        'ADD_USER': stamp_user,
        'CHG_DATE': now_ts,
        'CHG_USER': stamp_user,
    })


def _new_code(name):
    prefix = 'SZP-' + _base_letters(name) + '-'
    seed = datetime.datetime.now().microsecond
    for attempt in range(200):
        code = prefix + ('%02d' % ((seed + attempt * 7) % 100))
        if db.query_one('SELECT CODE FROM ' + db.t('SURZ_DISCOUNT')
                        + ' WHERE UPPER(CODE) = :c', {'c': code}) is None:
            return code
    return ''


def run(args):
    try:
        user_id, roles = _caller(args)
        if roles is not None and not any(r in _ADMIN_ROLES for r in roles):
            return {'error': 'Only an admin can approve a partner.'}

        partner_id = _text(_pick(args, 'PARTNER_ID', 'partner_id'))
        if not partner_id:
            return {'error': 'The partner id is missing.'}
        row = db.query_one(
            'SELECT PARTNER_ID, PARTNER_NAME, EMAIL, STATUS, REGISTRY_ID, '
            'DISCOUNT_CODE, DISCOUNT_PCT FROM ' + db.t('SURZ_PARTNER')
            + ' WHERE PARTNER_ID = :p', {'p': partner_id})
        if row is None:
            return {'error': 'Partner ' + partner_id + ' was not found.'}
        if _text(row['STATUS']).upper() != 'PENDING':
            return {'error': 'Only a PENDING application can be approved.'}

        name = _text(row['PARTNER_NAME'])
        email = _text(row['EMAIL'])
        # The admin's choice ON SCREEN wins over what was last saved: the
        # action posts the stored row overlaid with the form, so a code / %
        # typed and not yet saved still counts. Everything else (STATUS,
        # REGISTRY_ID) comes from the stored row above.
        typed_code = _pick(args, 'DISCOUNT_CODE', 'discount_code')
        typed_pct = _pick(args, 'DISCOUNT_PCT', 'discount_pct')
        code = _text(typed_code if typed_code is not None else row['DISCOUNT_CODE'])
        # The screen wins even when the admin CLEARED the % there (an existing
        # code then keeps its own %); the stored value is used only when the
        # payload carries no % at all.
        pct_raw = _text(typed_pct if typed_pct is not None else row['DISCOUNT_PCT'])
        pct = Decimal('0')
        if pct_raw:
            try:
                pct = Decimal(pct_raw)
            except Exception:
                return {'error': 'Discount % is not a number.'}
            if not pct.is_finite():
                return {'error': 'Discount % is not a number.'}
        # One rounding, matching the NUMBER(5,2) columns, used everywhere below.
        pct = pct.quantize(Decimal('0.01'), rounding='ROUND_HALF_UP')
        if pct < 0 or pct > 100:
            return {'error': 'Discount % must be between 0 and 100.'}
        now_ts = now()
        approver = user_id[:10] if user_id else None
        stamp_user = approver or _SYSTEM_USER

        # Codes match case-insensitively (a shopper's code is too), so a typed
        # `abc` finds a stored `ABC` / `Abc` and can never mint a near-duplicate
        # or slip past another partner's ownership.
        offer = None
        if code:
            offer = db.query_one(
                'SELECT CODE, PERCENT_OFF, PARTNER_ID FROM ' + db.t('SURZ_DISCOUNT')
                + ' WHERE UPPER(CODE) = :c', {'c': code.upper()})
        if offer is None:
            # No code yet (generate one) or a NEW code the admin typed:
            # either way it is created here with the given percentage.
            if pct <= 0:
                return {'error': 'Enter a Discount % between 0 and 100 (or pick '
                                 'a code this partner already owns) before approving.'}
            if code:
                code = code.upper()
                if not _valid_code(code):
                    return {'error': 'A new discount code may use only letters, digits, '
                                     '- and _ (up to 24 characters).'}
            else:
                code = _new_code(name)
                if not code:
                    return {'error': 'Could not generate a unique discount code. Try again.'}
            try:
                _insert_code(code, pct, partner_id, name, stamp_user, now_ts)
            except Exception as exc:
                # The action rolls back either way, nothing is half-written.
                # Only a key clash means another approval took the code a
                # moment ago (re-reading is not possible: the failed statement
                # has aborted the transaction).
                log('surz_partner_approve: insert of code ' + code + ' failed: ' + str(exc))
                reason = str(exc).lower()
                if 'duplicate' in reason or 'unique' in reason:
                    return {'error': 'Discount code ' + code + ' was just taken. Choose '
                                     'another code and approve again.'}
                return {'error': 'Could not create discount code ' + code
                                 + '. Please try again.'}
        else:
            code = _text(offer['CODE'])          # the stored spelling
            owner = _text(offer['PARTNER_ID'])
            if not owner:
                # A store-wide promo (no partner) is never handed to a partner,
                # and its percentage is never changed from here.
                return {'error': 'Discount code ' + code + ' is a store-wide code, not a '
                                 'partner code. Type a new code, or leave it blank to '
                                 'generate one.'}
            if owner != partner_id:
                return {'error': 'This code belongs to another partner.'}
            changes_offer = {
                'PARTNER_NAME': name[:120],
                'IS_ACTIVE': 'Y',
                'CHG_DATE': now_ts,
                'CHG_USER': stamp_user,
            }
            if pct > 0:
                # This partner's own code: it now gives exactly what was set.
                changes_offer['PERCENT_OFF'] = str(pct)
            else:
                pct = _dec(offer['PERCENT_OFF']).quantize(Decimal('0.01'), rounding='ROUND_HALF_UP')
            if pct <= 0:
                return {'error': 'The discount code has no percentage; enter a Discount %.'}
            db.update('SURZ_DISCOUNT', changes_offer, {'CODE': code})

        qr_url = _QR_BASE + _encode(code)

        # REGISTRY_ID CONTRACT: the applicant's OWN REGISTRY_ID (stamped by row
        # security when they applied) wins. The SURZ_CUSTOMER-by-e-mail match is
        # a FALLBACK only, used solely when the application's REGISTRY_ID is empty.
        registry_id = _text(row['REGISTRY_ID'])
        registry_source = 'application' if registry_id else 'none'
        if not registry_id and email:
            try:
                cust = db.query_one(
                    'SELECT REGISTRY_ID FROM ' + db.t('SURZ_CUSTOMER')
                    + ' WHERE EMAIL = :e AND REGISTRY_ID IS NOT NULL', {'e': email})
                if cust is not None:
                    registry_id = _text(cust['REGISTRY_ID'])
                    if registry_id:
                        registry_source = 'customer-by-email'
            except Exception as exc:
                log('surz_partner_approve: registry lookup skipped: ' + str(exc))
        log('surz_partner_approve: ' + partner_id + ' registry source = '
            + registry_source)

        changes = {
            'STATUS': 'APPROVED',
            'APPROVED_ON': now_ts,
            'APPROVED_BY': approver,
            'DISCOUNT_CODE': code,
            'DISCOUNT_PCT': str(pct),
            'QR_URL': qr_url,
            'REJECT_REASON': None,
            'CHG_DATE': now_ts,
            'CHG_USER': stamp_user,
        }
        if registry_id:
            changes['REGISTRY_ID'] = registry_id
        db.update('SURZ_PARTNER', changes, {'PARTNER_ID': partner_id})

        # BACKFILL: orders placed with this partner's code before the account was
        # known carry no PARTNER_REGISTRY_ID; stamp them so the creator sees them.
        # Best effort: a failure is logged and never rolls the approval back.
        if registry_id:
            try:
                db.execute(
                    'UPDATE ' + db.t('SURZ_ORDER')
                    + ' SET PARTNER_REGISTRY_ID = :r WHERE PARTNER_ID = :p '
                    "AND (PARTNER_REGISTRY_ID IS NULL OR PARTNER_REGISTRY_ID = '')",
                    {'r': registry_id, 'p': partner_id})
            except Exception as exc:
                log('surz_partner_approve: order backfill failed for '
                    + partner_id + ': ' + str(exc))

        # PARTNER ROLE: the approved partner gets the functional role 'partner'
        # on the app (user_id = the REGISTRY_ID the record stores). Best effort:
        # a failure is logged and never rolls the approval back.
        if registry_id:
            try:
                granted = api.grant_role(registry_id, 'partner')
                log('surz_partner_approve: grant_role(partner) for ' + partner_id
                    + ' -> ' + str(granted))
            except Exception as exc:
                log('surz_partner_approve: could not grant role partner to '
                    + partner_id + ': ' + str(exc))
        else:
            log('surz_partner_approve: ' + partner_id + ' has no REGISTRY_ID yet; '
                'the partner role will be granted once the account is known')

        payload = {
            'partner_id': partner_id,
            'partner_name': name,
            'email': email,
            'discount_code': code,
            'discount_pct': _pct_text(pct),
            'qr_url': qr_url,
            'portal_url': _PARTNER_PORTAL_URL,
        }
        if not email:
            log('surz_partner_approve: ' + partner_id + ' has no e-mail; welcome not sent')
        else:
            try:
                emitted = api.emit_event(_EVENT_NAME, payload)
                if isinstance(emitted, dict) and emitted.get('ok') is True:
                    db.update('SURZ_PARTNER', {'WELCOME_QUEUED_ON': now()},
                              {'PARTNER_ID': partner_id})
                else:
                    log('surz_partner_approve: emit of ' + _EVENT_NAME + ' for '
                        + partner_id + ' not confirmed (' + str(emitted)
                        + '); WELCOME_QUEUED_ON not stamped')
            except Exception as exc:
                log('surz_partner_approve: could not emit ' + _EVENT_NAME
                    + ' for ' + partner_id + ': ' + str(exc))

        return {'message': 'Partner approved. Code ' + code + ' issued.'}
    except Exception as exc:
        log('surz_partner_approve: failed: ' + str(exc))
        return {'error': 'Could not approve the partner: ' + str(exc)}
