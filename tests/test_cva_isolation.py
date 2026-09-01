# -*- coding: utf-8 -*-
from .common import CvaCase


class TestCvaIsolation(CvaCase):
    """El ajuste JAMÁS toca los datos reales: precios, descuentos, impuestos,
    totales, facturas, pagos, conciliaciones, estado ni flujo."""

    def test_01_natives_untouched(self):
        order = self._make_order(price=100.0, qty=2.0, discount=5.0,
                                 taxes=self.tax16)
        order.action_confirm()
        invoice = order._create_invoices()
        invoice.action_post()
        register = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({})
        payment = register._create_payments()[0]
        line = self._product_lines(order)
        snapshot = {
            'state': order.state,
            'price_unit': line.price_unit,
            'discount': line.discount,
            'price_subtotal': line.price_subtotal,
            'price_total': line.price_total,
            'amount_untaxed': order.amount_untaxed,
            'amount_tax': order.amount_tax,
            'amount_total': order.amount_total,
            'inv_total': invoice.amount_total,
            'inv_residual': invoice.amount_residual,
            'pay_amount': payment.amount,
            'pay_state': payment.state,
        }
        self._apply(order, 40.0)
        self._apply(order, 15.0, scope='lines', line_ids=[line.id])
        self._reset(order)
        self._apply(order, 40.0)
        self.assertEqual(order.state, snapshot['state'])
        self.assertAlmostEqual(line.price_unit, snapshot['price_unit'])
        self.assertAlmostEqual(line.discount, snapshot['discount'])
        self.assertAlmostEqual(line.price_subtotal, snapshot['price_subtotal'])
        self.assertAlmostEqual(line.price_total, snapshot['price_total'])
        self.assertAlmostEqual(order.amount_untaxed, snapshot['amount_untaxed'])
        self.assertAlmostEqual(order.amount_tax, snapshot['amount_tax'])
        self.assertAlmostEqual(order.amount_total, snapshot['amount_total'])
        self.assertAlmostEqual(invoice.amount_total, snapshot['inv_total'])
        self.assertAlmostEqual(invoice.amount_residual, snapshot['inv_residual'])
        self.assertAlmostEqual(payment.amount, snapshot['pay_amount'])
        self.assertEqual(payment.state, snapshot['pay_state'])

    def test_02_payment_example_from_spec(self):
        """Orden $100, pago $100, ajuste 40%: registrado 100 / pago 100 /
        administrativo 60 / diferencia 40. Sin saldos ni movimientos."""
        order = self._make_order(price=100.0)
        order.action_confirm()
        invoice = order._create_invoices()
        invoice.action_post()
        register = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({})
        payment = register._create_payments()[0]
        self._apply(order, 40.0)
        self.assertAlmostEqual(order.amount_total, 100.0)
        self.assertAlmostEqual(payment.amount, 100.0)
        self.assertAlmostEqual(order.x_cva_amount_total, 60.0)
        self.assertAlmostEqual(order.x_cva_amount_diff, 40.0)
        self.assertAlmostEqual(payment.x_cva_amount, 60.0, places=2)
        # el ajuste no tocó la contabilidad: el pago sigue in_process (sin
        # asiento en este build) y el residual de la factura sigue íntegro
        self.assertIn(payment.state, ('in_process', 'paid', 'posted'))
        self.assertAlmostEqual(invoice.amount_residual, 100.0)
        self.assertIn(invoice.payment_state, ('in_payment', 'paid', 'not_paid'))

    def test_03_copy_starts_clean(self):
        order = self._make_order(price=100.0)
        self._apply(order, 40.0)
        copy = order.copy()
        self.assertFalse(copy.x_cva_active)
        self.assertAlmostEqual(copy.x_cva_percent, 0.0)
        self.assertEqual(copy.x_cva_state, 'none')
        line = self._product_lines(copy)
        self.assertFalse(line.x_cva_has_override)
        self.assertAlmostEqual(line.x_cva_percent, 0.0)

    def test_04_client_documents_stay_real(self):
        """El render normal (sin ruta interactiva) del reporte de la orden es
        SIEMPRE real, para cualquier usuario."""
        order = self._make_order(price=333.0, qty=3.0)
        self._apply(order, 40.0)
        for user in (self.user_salesman, self.user_consulta, self.env.user):
            html = self.env['ir.actions.report'].with_user(user) \
                ._render_qweb_html('sale.report_saleorder', [order.id])[0]
            html = html.decode('utf-8') if isinstance(html, bytes) else str(html)
            self.assertIn('999.00', html)
            self.assertNotIn('599.40', html)

    def test_05_no_business_side_effects(self):
        """Aplicar el ajuste no crea facturas, pagos, asientos ni entregas."""
        order = self._make_order(price=100.0, taxes=self.tax16)
        order.action_confirm()
        moves_before = self.env['account.move'].search_count([])
        payments_before = self.env['account.payment'].search_count([])
        pickings_before = order.delivery_count if 'delivery_count' in order._fields else 0
        self._apply(order, 40.0)
        self._reset(order)
        self.assertEqual(self.env['account.move'].search_count([]), moves_before)
        self.assertEqual(self.env['account.payment'].search_count([]), payments_before)
        if 'delivery_count' in order._fields:
            self.assertEqual(order.delivery_count, pickings_before)
