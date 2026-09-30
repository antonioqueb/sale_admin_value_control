# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError

from .common import CvaCase


class TestCvaInvoiced(CvaCase):

    def _wizard(self, order):
        return self.env['sale.cva.apply.wizard'].with_user(self.user_manager) \
            .with_context(default_order_id=order.id).create({'order_id': order.id})

    def test_01_save_invoiced_keeps_line_percents(self):
        """Botón único: si solo se captura Facturado, no se re-aplica el
        ajuste (los % por línea se conservan y no se escribe historial)."""
        order = self._make_order(n_lines=2)
        line_a, line_b = order.order_line
        self._apply(order, 0.0, scope='lines',
                    line_percents={line_a.id: 20.0, line_b.id: 10.0})
        History = self.env['sale.cva.history'].sudo()
        n_history = History.search_count([('order_id', '=', order.id)])
        wiz = self._wizard(order)
        # Con % por línea el wizard abre respetándolos.
        self.assertTrue(wiz.keep_line_overrides)
        wiz.line_ids.filtered(lambda w: w.line_id == line_a).invoiced_amount = 80.0
        # Total de referencia: suma de lo capturado, sin tocar los importes.
        total_adm_before = wiz.total_adm_new
        self.assertAlmostEqual(wiz.total_invoiced, 80.0)
        self.assertEqual(wiz.invoiced_lines_label, '1 de 2 líneas')
        self.assertAlmostEqual(wiz.total_adm_new, total_adm_before)
        self.assertFalse(wiz._cva_percent_changes())
        wiz.action_confirm()
        self.assertAlmostEqual(line_a.x_cva_invoiced_amount, 80.0)
        self.assertAlmostEqual(line_b.x_cva_invoiced_amount, 0.0)
        self.assertAlmostEqual(line_a.x_cva_percent, 20.0)
        self.assertAlmostEqual(line_b.x_cva_percent, 10.0)
        self.assertEqual(
            History.search_count([('order_id', '=', order.id)]), n_history)
        # Al reabrir, el wizard trae lo facturado.
        wiz2 = self._wizard(order)
        self.assertAlmostEqual(
            wiz2.line_ids.filtered(lambda w: w.line_id == line_a).invoiced_amount, 80.0)

    def test_02_apply_also_saves_invoiced(self):
        order = self._make_order()
        wiz = self._wizard(order)
        wiz.percent = 10.0
        wiz.line_ids.invoiced_amount = 90.0
        wiz.action_confirm()
        self.assertAlmostEqual(order.order_line.x_cva_invoiced_amount, 90.0)
        self.assertAlmostEqual(order.order_line.x_cva_percent, 10.0)

    def test_03_consulta_cannot_write_invoiced(self):
        order = self._make_order()
        with self.assertRaises(AccessError):
            order.order_line.with_user(self.user_consulta).write(
                {'x_cva_invoiced_amount': 50.0})

    def test_04_margins_without_cost_are_empty(self):
        """Sin costo all-in (servicio) la utilidad queda en 0, no infinita."""
        order = self._make_order()
        wline = self._wizard(order).line_ids
        self.assertEqual(wline.cost_all_in, 0.0)
        self.assertEqual(wline.margin_current, 0.0)
        self.assertEqual(wline.margin_new, 0.0)
