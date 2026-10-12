# project: Surzion_Store
# object_name: surz_order
# object_type: T
# event: post_commit
# function_name: surz_order_confirmation
# language: python
# description: Email the order confirmation
# functional_specification:
# After commit, email the customer at EMAIL a confirmation naming ORDER_NO, the
# lines and TOTAL_AMOUNT, and whether payment is still due. Never block the
# save: log and return on any failure.
#
# SENT ONCE, when the order is first placed. post_commit fires on EVERY
# batch save, so without the action guard below, stamping a courier, a
# tracking number or a payment reference re-sends the whole confirmation to
# the customer. Neither spec ever asked for repeat sends.
#
# WHETHER PAYMENT IS DUE IS DECIDED BY THE AMOUNT, never by PAY_STATUS: a
# status stamped 'PAID' over a part-payment must not tell a customer they
# owe nothing. The status only chooses the wording.
#
# Every money value in the event payload is an exact 2-decimal STRING, so a
# flow template renders 6750.30 rather than the 6750.3 a float prints.

# The engine's only sanctioned side-effect channel is api.emit_event, which
# hands the message to IOFlow; the flow bound to this event name is what puts it
# in the customer's inbox. The event must exist in the project's Integration
# Design — until it does, emit_event raises and this function logs and returns,
# exactly as the specification requires. Nothing here may ever reach the caller
# as a failure: the order is already committed.
#
# STATUS: the 'surz_order_confirmed' outbound event is being added to the
# project's Integration Design. Until it lands this function is CORRECT AND
# INERT — it assembles the whole message, finds no event, logs, and returns.
# Nothing here changes when the event arrives.
#
# `api` IS bound on this path. executor.execute_transaction_batch carries
# @_with_ident_case, which publishes ctx + project into the BL call-context for
# the WHOLE call — and _run_post_commit is invoked inside that call, after the
# commit — so _build_runtime_api returns a live RuntimeApi. The only callers
# that get the placeholder instead are ones with no ctx at all: the deploy
# compile-check and a direct test invoke.
_EVENT_NAME = 'surz_order_confirmed'
# Only ever used to choose WORDING — never to decide whether money is owed.
_PAID_STATES = ('PAID', 'CAPTURED', 'SETTLED', 'COMPLETED', 'SUCCESS')


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


def _money(value):
    if value is None or value == '':
        return Decimal('0')
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'), rounding='ROUND_HALF_UP')
    except Exception:
        return Decimal('0')


def _qty(value):
    amount = _money(value)
    whole = amount.quantize(Decimal('1'), rounding='ROUND_DOWN')
    if amount == whole:
        return str(int(whole))
    return str(amount)


def _as_text(value):
    if value is None:
        return ''
    if isinstance(value, datetime.datetime):
        return value.strftime('%Y-%m-%d %H:%M')
    if isinstance(value, datetime.date):
        return value.strftime('%Y-%m-%d')
    return str(value)


def run(args):
    order_no = ''
    try:
        # A confirmation is for a NEW order. Every later save of the same
        # record — a courier, a tracking number, the payment write-back —
        # arrives here too, and re-mailing the customer each time is not a
        # confirmation, it is noise. A status-change notice would be its
        # own event, with its own wording.
        if _text(args.get('action')).lower() != 'add':
            return None
        header = args.get('header') or {}
        order_no = _text(_pick(header, 'ORDER_NO', 'order_no')) or _text(args.get('txn_id'))
        if not order_no:
            log('surz_order_confirmation: no order number in the payload — skipped')
            return None

        # Read the order back: pre_commit rewrote the money on the row after the
        # payload in `header` was built, so the committed row is the only place
        # the confirmed totals actually are.
        order = db.query_one(
            'SELECT ORDER_NO, ORDER_DATE, CUSTOMER_NAME, EMAIL, PHONE, '
            'SHIP_ADDRESS, SUBTOTAL, DISCOUNT_AMT, GST_AMT, SHIPPING_AMT, '
            'TOTAL_AMOUNT, PAY_STATUS, PAY_METHOD, PAID_AMOUNT '
            'FROM ' + db.t('SURZ_ORDER') + ' WHERE ORDER_NO = :order_no',
            {'order_no': order_no},
        )
        if order is None:
            log('surz_order_confirmation: order ' + order_no + ' not found — skipped')
            return None

        email = _text(order['EMAIL'])
        if not email:
            log('surz_order_confirmation: order ' + order_no
                + ' has no e-mail address — nothing sent')
            return None

        rows = db.query(
            'SELECT LINE_NO, PRODUCT_CODE, PRODUCT_NAME, QTY, UNIT_PRICE, LINE_TOTAL '
            'FROM ' + db.t('SURZ_ORDER_LINE') + ' WHERE ORDER_NO = :order_no '
            'ORDER BY LINE_NO',
            {'order_no': order_no},
        )

        lines = []
        printed = []
        for row in rows or []:
            name = _text(row['PRODUCT_NAME']) or _text(row['PRODUCT_CODE'])
            qty = _qty(row['QTY'])
            line_total = _money(row['LINE_TOTAL'])
            lines.append({
                'line_no': _as_text(row['LINE_NO']),
                'product_code': _text(row['PRODUCT_CODE']),
                'product_name': name,
                'qty': qty,
                'unit_price': str(_money(row['UNIT_PRICE'])),
                'line_total': str(line_total),
            })
            printed.append(qty + ' x ' + name + '  INR ' + str(line_total))

        total = _money(order['TOTAL_AMOUNT'])
        paid = _money(order['PAID_AMOUNT'])
        pay_status = _text(order['PAY_STATUS']).upper()
        due = total - paid
        if due < 0:
            due = Decimal('0')
        # The AMOUNT decides, not the status. A PAY_STATUS of 'PAID' over a
        # part-payment would otherwise suppress a real outstanding balance
        # and thank the customer for settling in full.
        payment_due = due > 0

        if payment_due:
            payment_line = ('Payment of INR ' + str(due) + ' is still due'
                            + (' (status ' + pay_status + ')' if pay_status else '')
                            + '.')
        elif pay_status in _PAID_STATES:
            payment_line = 'Payment received in full. Thank you.'
        else:
            payment_line = 'Nothing further is due on this order.'

        customer = _text(order['CUSTOMER_NAME']) or 'Customer'
        body = '\n'.join(
            ['Dear ' + customer + ',',
             '',
             'Thank you for your order ' + order_no
             + ' placed on ' + _as_text(order['ORDER_DATE']) + '.',
             '']
            + printed
            + ['',
               'Order total: INR ' + str(total),
               payment_line,
               '',
               'Surzion Surgical Instruments']
        )

        api.emit_event(_EVENT_NAME, {
            'order_no': order_no,
            'order_date': _as_text(order['ORDER_DATE']),
            'email': email,
            'customer_name': customer,
            'phone': _text(order['PHONE']),
            'ship_address': _text(order['SHIP_ADDRESS']),
            # Exact 2-decimal strings: a template rendering {{total_amount}}
            # must print 6750.30, and a float prints 6750.3.
            'subtotal': str(_money(order['SUBTOTAL'])),
            'discount_amt': str(_money(order['DISCOUNT_AMT'])),
            'gst_amt': str(_money(order['GST_AMT'])),
            'shipping_amt': str(_money(order['SHIPPING_AMT'])),
            'total_amount': str(total),
            'paid_amount': str(paid),
            'amount_due': str(due),
            'payment_due': payment_due,
            'pay_status': pay_status,
            'pay_method': _text(order['PAY_METHOD']),
            'lines': lines,
            'subject': 'Your Surzion order ' + order_no,
            'body': body,
        })
        log('surz_order_confirmation: confirmation for ' + order_no
            + ' queued for ' + email)
    except Exception as exc:
        # A post_commit failure must never be reported as a save failure: the
        # order is committed and the customer has been charged nothing by this.
        log('surz_order_confirmation: could not send the confirmation for '
            + (order_no or '(unknown order)') + ': ' + str(exc))
    return None
