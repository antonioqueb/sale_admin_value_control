# -*- coding: utf-8 -*-
from odoo.exceptions import UserError

from .common import CvaCase


class TestCvaHistory(CvaCase):

    def test_01_history_entries(self):
        order = self._make_order(price=100.0, n_lines=2)
        l1, _l2 = self._product_lines(order)
        self._apply(order, 40.0, reason='PRIMERA')
        self._apply(order, 20.0, scope='lines', line_ids=[l1.id], reason='LINEA')
        self._reset(order, reason='BORRON')
        self._apply(order, 10.0, reason='DE NUEVO')
        history = order.sudo().x_cva_history_ids.sorted('id')
        self.assertEqual(len(history), 4)
        self.assertEqual(history.mapped('action'),
                         ['apply_order', 'apply_lines', 'reset', 'apply_order'])
        first = history[0]
        self.assertAlmostEqual(first.percent_before, 0.0)
        self.assertAlmostEqual(first.percent_after, 40.0)
        self.assertAlmostEqual(first.amount_before, 200.0)
        self.assertAlmostEqual(first.amount_after, 120.0)
        self.assertAlmostEqual(first.amount_reference, 200.0)
        self.assertEqual(first.user_id, self.user_manager)
        self.assertEqual(len(first.line_ids), 2)
        line_entry = first.line_ids[0]
        self.assertAlmostEqual(line_entry.percent_before, 0.0)
        self.assertAlmostEqual(line_entry.percent_after, 40.0)
        self.assertAlmostEqual(line_entry.subtotal_after, 60.0)
        reset_entry = history[2]
        self.assertAlmostEqual(reset_entry.percent_after, 0.0)
        self.assertAlmostEqual(reset_entry.amount_after, 200.0)

    def test_02_history_immutable(self):
        order = self._make_order(price=100.0)
        self._apply(order, 40.0)
        entry = order.sudo().x_cva_history_ids
        with self.assertRaises(UserError):
            entry.sudo().write({'reason': 'HACKEADO'})
        with self.assertRaises(UserError):
            entry.sudo().unlink()
        with self.assertRaises(UserError):
            entry.line_ids.sudo().write({'percent_after': 1.0})
        with self.assertRaises(UserError):
            entry.line_ids.sudo().unlink()

    def test_03_reason_optional_and_keeps_history(self):
        order = self._make_order(price=100.0)
        # el motivo es opcional: vacío o None no bloquean ni el ajuste ni el
        # restablecimiento, y el historial se sigue escribiendo
        self._apply(order, 40.0, reason='')
        self.assertEqual(order.x_cva_reason, '')
        order.with_user(self.user_manager)._cva_reset('')
        self.assertEqual(order.x_cva_state, 'reset')
        self._apply(order, 40.0, reason=None)
        self.assertEqual(len(order.sudo().x_cva_history_ids), 3)
        count_before = len(order.sudo().x_cva_history_ids)
        self._reset(order, reason='MOTIVO VALIDO')
        self.assertEqual(order.x_cva_state, 'reset')
        self.assertFalse(order.x_cva_active)
        self.assertAlmostEqual(order.x_cva_percent, 0.0)
        self.assertAlmostEqual(order.x_cva_amount_total, order.amount_total)
        self.assertEqual(len(order.sudo().x_cva_history_ids), count_before + 1)

    def test_04_wizard_reset(self):
        order = self._make_order(price=100.0)
        self._apply(order, 40.0)
        wiz = self.env['sale.cva.reset.wizard'].with_user(self.user_manager) \
            .create({'order_id': order.id, 'reason': 'VIA WIZARD'})
        self.assertIn(order.name, wiz.summary)
        wiz.action_confirm()
        self.assertEqual(order.x_cva_state, 'reset')
