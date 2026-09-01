# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import CvaCase


class TestCvaLens(CvaCase):
    """La lente presenta TODO ajustado al Administrador CVA y a nadie más."""

    def setUp(self):
        super().setUp()
        self.order = self._make_order(price=100.0)
        self._apply(self.order, 40.0)

    def _mgr(self, model):
        return self.env[model].with_user(self.user_manager)

    def test_01_web_read_substitution(self):
        vals = self._mgr('sale.order').browse(self.order.id).web_read(
            {'amount_total': {}, 'amount_untaxed': {}, 'name': {}})[0]
        self.assertAlmostEqual(vals['amount_total'], 60.0)
        self.assertAlmostEqual(vals['amount_untaxed'], 60.0)
        line = self._product_lines(self.order)
        lvals = self._mgr('sale.order.line').browse(line.id).web_read(
            {'price_unit': {}, 'price_subtotal': {}, 'price_total': {}})[0]
        self.assertAlmostEqual(lvals['price_unit'], 60.0)
        self.assertAlmostEqual(lvals['price_subtotal'], 60.0)
        # anidado: la orden con sus líneas
        nested = self._mgr('sale.order').browse(self.order.id).web_read(
            {'order_line': {'fields': {'price_unit': {}}}})[0]
        self.assertAlmostEqual(nested['order_line'][0]['price_unit'], 60.0)

    def test_02_other_users_see_real(self):
        vals = self.env['sale.order'].with_user(self.user_consulta) \
            .browse(self.order.id).web_read({'amount_total': {}})[0]
        self.assertAlmostEqual(vals['amount_total'], 100.0)
        vals = self.env['sale.order'].with_user(self.user_salesman) \
            .browse(self.order.id).web_read({'amount_total': {}})[0]
        self.assertAlmostEqual(vals['amount_total'], 100.0)

    def test_03_toggle_off(self):
        self.env['res.users'].with_user(self.user_manager) \
            .action_cva_toggle_lens()
        vals = self._mgr('sale.order').browse(self.order.id).web_read(
            {'amount_total': {}})[0]
        self.assertAlmostEqual(vals['amount_total'], 100.0)
        self.env['res.users'].with_user(self.user_manager) \
            .action_cva_toggle_lens()
        vals = self._mgr('sale.order').browse(self.order.id).web_read(
            {'amount_total': {}})[0]
        self.assertAlmostEqual(vals['amount_total'], 60.0)

    def test_04_read_group_substitution(self):
        groups = self._mgr('sale.order').formatted_read_group(
            [('id', '=', self.order.id)],
            groupby=['partner_id'], aggregates=['amount_total:sum'])
        self.assertAlmostEqual(groups[0]['amount_total:sum'], 60.0)
        groups = self.env['sale.order'].with_user(self.user_salesman) \
            .formatted_read_group(
                [('id', '=', self.order.id)],
                groupby=['partner_id'], aggregates=['amount_total:sum'])
        self.assertAlmostEqual(groups[0]['amount_total:sum'], 100.0)

    def test_05_export_substitution(self):
        data = self._mgr('sale.order').browse(self.order.id).export_data(
            ['name', 'amount_total'])['datas']
        self.assertAlmostEqual(float(data[0][1]), 60.0)
        data = self.env['sale.order'].with_user(self.user_consulta) \
            .browse(self.order.id).export_data(
            ['name', 'amount_total'])['datas']
        self.assertAlmostEqual(float(data[0][1]), 100.0)

    def test_06_web_save_guard(self):
        line = self._product_lines(self.order)
        with self.assertRaises(UserError):
            self._mgr('sale.order').browse(self.order.id).web_save(
                {'order_line': [(1, line.id, {'price_unit': 60.0})]},
                {'id': {}})
        # guardar el MISMO valor real no bloquea (campo no tocado de verdad)
        self._mgr('sale.order').browse(self.order.id).web_save(
            {'order_line': [(1, line.id, {'price_unit': 100.0})]}, {'id': {}})
        # y el ORM directo (lógica de negocio) nunca se bloquea
        line.with_user(self.user_manager).write({'price_unit': 120.0})
        self.assertAlmostEqual(line.price_unit, 120.0)

    def test_07_search_read_substitution(self):
        res = self._mgr('sale.order').search_read(
            [('id', '=', self.order.id)], ['amount_total'])
        self.assertAlmostEqual(res[0]['amount_total'], 60.0)

    def test_08_invoice_and_payment_lens(self):
        order = self.order
        order.action_confirm()
        invoice = order._create_invoices()
        invoice.action_post()
        self.assertAlmostEqual(invoice.x_cva_amount_total, 60.0)
        self.assertAlmostEqual(invoice.amount_total, 100.0)
        ivals = self._mgr('account.move').browse(invoice.id).web_read(
            {'amount_total': {}, 'amount_residual': {}})[0]
        self.assertAlmostEqual(ivals['amount_total'], 60.0)
        self.assertAlmostEqual(ivals['amount_residual'], 60.0)
        # pago completo real de $100
        register = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({})
        payments = register._create_payments()
        payment = payments[0]
        self.assertAlmostEqual(payment.amount, 100.0)
        self.assertAlmostEqual(payment.x_cva_amount, 60.0, places=2)
        pvals = self._mgr('account.payment').browse(payment.id).web_read(
            {'amount': {}})[0]
        self.assertAlmostEqual(pvals['amount'], 60.0, places=2)
        # indicadores de la orden
        self.assertAlmostEqual(order.x_cva_paid_amount, 100.0)
        self.assertAlmostEqual(order.x_cva_paid_amount_adm, 60.0, places=2)
        self.assertAlmostEqual(order.x_cva_balance_adm, 0.0, places=2)

    def test_09_print_lens_and_real(self):
        order = self._make_order(price=333.0, qty=3.0)
        self._apply(order, 40.0)  # real 999.00 -> adm 599.40
        Report = self.env['ir.actions.report']
        html_lens = Report.with_user(self.user_manager).with_context(
            cva_lens_print=True)._render_qweb_html(
            'sale.report_saleorder', [order.id])[0]
        html_lens = html_lens.decode('utf-8') if isinstance(html_lens, bytes) else str(html_lens)
        self.assertIn('599.40', html_lens)
        self.assertNotIn('999.00', html_lens)
        # sin contexto interactivo: real, incluso para el manager
        html_real = Report.with_user(self.user_manager)._render_qweb_html(
            'sale.report_saleorder', [order.id])[0]
        html_real = html_real.decode('utf-8') if isinstance(html_real, bytes) else str(html_real)
        self.assertIn('999.00', html_real)
        self.assertNotIn('599.40', html_real)
        # y para el vendedor siempre real aunque fuerce el contexto
        html_sm = Report.with_user(self.user_salesman).with_context(
            cva_lens_print=True)._render_qweb_html(
            'sale.report_saleorder', [order.id])[0]
        html_sm = html_sm.decode('utf-8') if isinstance(html_sm, bytes) else str(html_sm)
        self.assertIn('999.00', html_sm)

    def test_10_cash_receipt_lens(self):
        receipt = self.env['cash.receipt'].create({
            'partner_id': self.partner.id,
            'sale_order_ids': [(6, 0, self.order.ids)],
            'amount': 100.0,
        })
        rvals = self._mgr('cash.receipt').browse(receipt.id).web_read(
            {'amount': {}, 'total_orders_amount': {}})[0]
        self.assertAlmostEqual(rvals['amount'], 60.0, places=2)
        self.assertAlmostEqual(rvals['total_orders_amount'], 60.0, places=2)
        self.assertAlmostEqual(receipt.amount, 100.0)

    def test_11_sale_report_columns(self):
        self.order.action_confirm()
        self.env.flush_all()
        rows = self.env['sale.report'].with_user(self.user_consulta).search_read(
            [('partner_id', '=', self.partner.id)],
            ['price_subtotal', 'x_cva_price_subtotal', 'x_cva_amount_diff'])
        total_ref = sum(r['price_subtotal'] for r in rows)
        total_adm = sum(r['x_cva_price_subtotal'] for r in rows)
        diff = sum(r['x_cva_amount_diff'] for r in rows)
        self.assertAlmostEqual(total_ref, 100.0, places=2)
        self.assertAlmostEqual(total_adm, 60.0, places=2)
        self.assertAlmostEqual(diff, 40.0, places=2)
