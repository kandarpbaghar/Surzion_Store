# project: Surzion_Store
# object_name: surz_order
# object_type: T
# form_no: 2 (SURZ_ORDER_LINE)
# field_name: line_total (also bound on qty and unit_price)
# event: field_item_change
# function_name: surz_order_line_total
# language: python
# description: Recompute the line total
# functional_specification:
# On a change of QTY or UNIT_PRICE set LINE_TOTAL = round(QTY * UNIT_PRICE, 2),
# computed in Decimal so the printed rupee figure is exact. Refuse QTY < 1 with
# a field error on QTY.
#
# THE REFUSAL CARRIES NO COLUMN UPDATES, deliberately. A structured `errors`
# return is answered by executor._normalize_ic_result's `_apply_entries`, which
# hard-returns `{"ok": False, "updates": {}, "errors": [...]}` before it can
# reach the branch that honours `updates` beside an error — so a LINE_TOTAL
# returned here would be dropped, and code that appears to clear the stale
# total while doing nothing is worse than code that does not pretend to.
# (`_apply_entries` also rebuilds the flat `error` key from the list, so
# returning one alongside is dead weight.)
#
# BOUND TO QTY, UNIT_PRICE AND LINE_TOTAL. An item_change fires only for the
# column that was actually edited, and LINE_TOTAL is protected, so binding it
# there alone meant this could never run. Choosing a PRODUCT is covered by the
# product_code rule's own expression fill — one item_change never cascades into
# another.
#
# DISCOUNT PREVIEW: the same return also sets DISC_PCT (= header
# DISCOUNT_PCT_INFO, blank = 0), DISC_AMT = round(LINE_TOTAL * DISC_PCT / 100, 2)
# and TAXABLE_VALUE = LINE_TOTAL - DISC_AMT, as 2dp strings, read from
# args['header']. When the payload carries no header the discount columns are
# NOT returned (never overwritten with a guessed 0). surz_price_order is the
# authority at save.
#
# THE BLOCKING REFUSAL IS THE qty_min VALIDATION BESIDE IT, not this. An
# item_change is a best-effort cascade: the client logs `res.error` at debug
# level and lets the user carry on, so this return alone never stops a save.

_QTY_ERROR_CODE = 'SURZORDQTY1'
_QTY_ERROR_TEXT = 'Quantity must be at least 1.'


def _dec(value):
    """A payload value as a Decimal, without the float hop `to_number` takes.

    Money is never carried through a binary float here: the string the form
    sent becomes a Decimal directly, so 3 x 2250.10 is 6750.30 rather than
    6750.2999999999997 rounded back into shape.
    """
    if value is None or value == '':
        return Decimal('0')
    try:
        return Decimal(str(value).strip())
    except Exception:
        return Decimal('0')


def _money(amount):
    """Round to 2 dp HALF-UP, as a Decimal."""
    try:
        return amount.quantize(Decimal('0.01'), rounding='ROUND_HALF_UP')
    except Exception:
        return Decimal('0.00')


def _header_pct(args):
    """The header's DISCOUNT_PCT_INFO, or None when the payload does not carry
    the header. None means "unknown": the discount columns are then left alone
    rather than overwritten with a made-up 0 (the product_code rule fill and
    surz_price_order own them in that case)."""
    header = args.get('header')
    if not isinstance(header, dict):
        return None
    for key in header.keys():
        if isinstance(key, str) and key.lower() == 'discount_pct_info':
            pct = _dec(header[key])
            if pct < 0:
                return Decimal('0')
            if pct > 100:
                return Decimal('100')
            return pct
    return None


def run(args):
    try:
        # `to_number` for the COMPARISON only - a float is perfectly good at
        # deciding whether something is below 1.
        if to_number(args.get('QTY'), 0) < 1:
            return {'errors': [{
                'code': _QTY_ERROR_CODE,
                'field': 'qty',
                'type': 'E',
                'message': _QTY_ERROR_TEXT,
            }]}

        total = _money(_dec(args.get('QTY')) * _dec(args.get('UNIT_PRICE')))
        updates = {'line_total': str(total)}

        pct = _header_pct(args)
        if pct is not None:
            disc_amt = _money(total * pct / Decimal('100'))
            updates['disc_pct'] = str(_money(pct))
            updates['disc_amt'] = str(disc_amt)
            updates['taxable_value'] = str(_money(total - disc_amt))
        return {'updates': updates}
    except Exception as exc:
        log('surz_order_line_total: failed: ' + str(exc))
        return None
