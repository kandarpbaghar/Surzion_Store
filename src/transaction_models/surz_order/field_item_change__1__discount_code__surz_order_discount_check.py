# project: Surzion_Store
# object_name: surz_order
# object_type: T
# form_no: 1 (SURZ_ORDER)
# field_name: discount_code
# event: field_item_change
# function_name: surz_order_discount_check
# language: python
# description: Validate the typed discount code and show its percent before saving
# functional_specification:
# Blank code: clear DISCOUNT_PCT_INFO, PARTNER_ID, PARTNER_NAME, no error.
# Otherwise match the trimmed code CASE-INSENSITIVELY against SURZ_DISCOUNT.CODE;
# the row must be active (NULL/blank IS_ACTIVE counts as active, as in
# surz_price_order). A code owned by a partner counts only while that
# SURZ_PARTNER row is APPROVED. Unknown / inactive / unapproved-partner code:
# a blocking error on DISCOUNT_CODE ('This discount code is not valid.') AND the
# three fills cleared (the runtime honours `updates` beside a flat `error`; it
# does NOT beside a structured `errors` list, so the flat form is used).
# Valid code: DISCOUNT_CODE is normalised to the stored CODE, and
# DISCOUNT_PCT_INFO / PARTNER_ID / PARTNER_NAME are filled. VALID_FROM/VALID_TO
# and MIN_ORDER are NOT checked here (surz_price_order does at save).
# Read-only: writes nothing, never touches USAGE_COUNT.
#
# NOT DONE: refreshing the DISC_* columns of lines already on the form. The
# runtime hands a business-logic item_change only the current form's values (no
# line rows), and a `Detail2` section in the return ADDS rows rather than
# updating existing ones. Lines added or edited afterwards pick the percent up
# from the header; surz_price_order recomputes every line at save.

_NOT_VALID_TEXT = 'This discount code is not valid.'
_ACTIVE_VALUES = ('Y', 'YES', '1', 'T', 'TRUE')


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


def _cleared():
    return {'discount_pct_info': '', 'partner_id': '', 'partner_name': ''}


def _invalid():
    return {'error': _NOT_VALID_TEXT, 'updates': _cleared()}


def run(args):
    try:
        typed = _text(_pick(args, 'DISCOUNT_CODE', 'discount_code'))
        if not typed:
            return {'updates': _cleared()}

        offer = db.query_one(
            'SELECT CODE, PERCENT_OFF, IS_ACTIVE, PARTNER_ID, PARTNER_NAME FROM '
            + db.t('SURZ_DISCOUNT') + ' WHERE UPPER(CODE) = UPPER(:code) '
            'ORDER BY CODE',
            {'code': typed})
        if offer is None:
            return _invalid()
        active = _text(offer['IS_ACTIVE']).upper()
        if active and active not in _ACTIVE_VALUES:
            return _invalid()

        owner = _text(offer['PARTNER_ID'])
        partner_name = _text(offer['PARTNER_NAME'])
        if owner:
            partner = db.query_one(
                'SELECT STATUS, PARTNER_NAME FROM ' + db.t('SURZ_PARTNER')
                + ' WHERE PARTNER_ID = :p', {'p': owner})
            if partner is None or _text(partner['STATUS']).upper() != 'APPROVED':
                return _invalid()
            if not partner_name:
                partner_name = _text(partner['PARTNER_NAME'])

        pct = offer['PERCENT_OFF']
        return {'updates': {
            'discount_code': _text(offer['CODE']),
            'discount_pct_info': '' if pct is None else str(pct),
            'partner_id': owner,
            'partner_name': partner_name if owner else '',
        }}
    except Exception as exc:
        log('surz_order_discount_check: failed: ' + str(exc))
        return None
