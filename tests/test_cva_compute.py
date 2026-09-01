# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError

from .common import CvaCase


class TestCvaCompute(CvaCase):

    def test_01_basic_40_percent(self):
        """$100 con 40% -> administrativo $60; el registrado sigue en $100."""
        order = self._make_order(price=100.0)
        self._apply(order, 40.0)
        line = self._product_lines(order)
        self.assertAlmostEqual(line.x_cva_percent, 40.0)
        self.assertAlmostEqual(line.x_cva_price_unit_ref, 100.0)
        self.assertAlmostEqual(line.x_cva_price_unit, 60.0)
        self.assertAlmostEqual(line.x_cva_price_subtotal, 60.0)
        self.assertAlmostEqual(order.x_cva_amount_total, 60.0)
        self.assertAlmostEqual(order.x_cva_amount_diff, 40.0)
        self.assertAlmostEqual(order.amount_total, 100.0)
        self.assertEqual(order.x_cva_state, 'applied')
        self.assertTrue(order.x_cva_active)
        self.assertEqual(order.x_cva_user_id, self.user_manager)

    def test_02_with_tax(self):
        order = self._make_order(price=100.0, taxes=self.tax16)
        self._apply(order, 40.0)
        self.assertAlmostEqual(order.amount_total, 116.0)
        self.assertAlmostEqual(order.x_cva_amount_untaxed, 60.0)
        self.assertAlmostEqual(order.x_cva_amount_tax, 9.6)
        self.assertAlmostEqual(order.x_cva_amount_total, 69.6)
        self.assertAlmostEqual(order.x_cva_amount_diff, 46.4)
        # el impuesto nativo no cambia
        self.assertAlmostEqual(order.amount_tax, 16.0)

    def test_03_commercial_discount_reference(self):
        """Referencia = precio neto del descuento comercial (decisión A)."""
        order = self._make_order(price=100.0, discount=10.0)
        self._apply(order, 40.0)
        line = self._product_lines(order)
        self.assertAlmostEqual(line.x_cva_price_unit_ref, 90.0)
        self.assertAlmostEqual(line.x_cva_price_unit, 54.0)
        self.assertAlmostEqual(line.x_cva_price_subtotal, 54.0)
        self.assertAlmostEqual(order.amount_total, 90.0)

    def test_04_line_override_precedence(self):
        order = self._make_order(price=100.0, n_lines=2)
        self._apply(order, 40.0)
        l1, l2 = self._product_lines(order)
        self._apply(order, 20.0, scope='lines', line_ids=[l1.id])
        self.assertAlmostEqual(l1.x_cva_percent, 20.0)
        self.assertFalse(l1.x_cva_percent_inherited)
        self.assertAlmostEqual(l1.x_cva_price_subtotal, 80.0)
        self.assertAlmostEqual(l2.x_cva_percent, 40.0)
        self.assertTrue(l2.x_cva_percent_inherited)
        self.assertAlmostEqual(order.x_cva_amount_total, 140.0)

    def test_05_apply_order_clears_overrides(self):
        order = self._make_order(price=100.0, n_lines=2)
        l1, _l2 = self._product_lines(order)
        self._apply(order, 20.0, scope='lines', line_ids=[l1.id])
        self._apply(order, 30.0)  # global limpia particulares (decisión B)
        self.assertFalse(l1.x_cva_has_override)
        self.assertAlmostEqual(l1.x_cva_percent, 30.0)
        # con keep_line_overrides el particular sobrevive
        self._apply(order, 20.0, scope='lines', line_ids=[l1.id])
        self._apply(order, 50.0, keep_line_overrides=True)
        self.assertTrue(l1.x_cva_has_override)
        self.assertAlmostEqual(l1.x_cva_percent, 20.0)

    def test_06_recompute_on_changes(self):
        order = self._make_order(price=100.0)
        self._apply(order, 40.0)
        line = self._product_lines(order)
        line.write({'product_uom_qty': 3.0})
        self.assertAlmostEqual(line.x_cva_price_subtotal, 180.0)
        line.write({'price_unit': 200.0})
        self.assertAlmostEqual(line.x_cva_price_subtotal, 360.0)
        line.write({'discount': 50.0})
        self.assertAlmostEqual(line.x_cva_price_subtotal, 180.0)
        line.write({'tax_ids': [(6, 0, self.tax16.ids)]})
        self.assertAlmostEqual(line.x_cva_price_total, 208.8)

    def test_07_bounds(self):
        order = self._make_order(price=100.0)
        with self.assertRaises(UserError):
            self._apply(order, -1.0)
        with self.assertRaises(UserError):
            self._apply(order, 101.0)
        line = self._product_lines(order)
        with self.assertRaises(ValidationError):
            line.with_user(self.user_manager).write(
                {'x_cva_has_override': True, 'x_cva_percent_override': 101.0})
        self._apply(order, 100.0)
        self.assertAlmostEqual(order.x_cva_amount_total, 0.0)
        self._apply(order, 0.0)
        self.assertAlmostEqual(order.x_cva_amount_total, order.amount_total)

    def test_08_sections_and_rounding(self):
        order = self._make_order(price=33.33, qty=3.0, with_section=True)
        self._apply(order, 33.33)
        section = order.order_line.filtered('display_type')
        self.assertAlmostEqual(section.x_cva_price_subtotal, 0.0)
        line = self._product_lines(order)
        expected = self.currency.round(
            self.currency.round(33.33 * 3) and (33.33 * (1 - 33.33 / 100.0)) * 3)
        self.assertAlmostEqual(line.x_cva_price_subtotal, expected, places=2)
        self.assertAlmostEqual(
            order.x_cva_amount_total, line.x_cva_price_total, places=2)

    def test_09_wizard_flow(self):
        order = self._make_order(price=100.0, n_lines=2)
        wiz = self.env['sale.cva.apply.wizard'].with_user(self.user_manager) \
            .with_context(default_order_id=order.id).create({
                'order_id': order.id,
                'scope': 'order',
                'percent': 40.0,
                'reason': 'VIA WIZARD',
            })
        self.assertEqual(len(wiz.line_ids), 2)
        self.assertAlmostEqual(wiz.total_ref, 200.0)
        self.assertAlmostEqual(wiz.total_adm_new, 120.0)
        wiz.action_confirm()
        self.assertAlmostEqual(order.x_cva_amount_total, 120.0)
        self.assertEqual(order.x_cva_reason, 'VIA WIZARD')
