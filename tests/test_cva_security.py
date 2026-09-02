# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError

from .common import CvaCase


class TestCvaSecurity(CvaCase):

    def setUp(self):
        super().setUp()
        self.order = self._make_order(price=100.0)
        self._apply(self.order, 40.0)

    # ------------------------------------------------------------------
    # Usuarios sin grupo (vendedor y administrador general de Odoo)
    # ------------------------------------------------------------------
    def _assert_no_access(self, user):
        order = self.order.with_user(user)
        with self.assertRaises(AccessError):
            order.read(['x_cva_percent'])
        with self.assertRaises(AccessError):
            order.write({'x_cva_percent': 10.0})
        self.assertNotIn('x_cva_percent',
                         self.env['sale.order'].with_user(user).fields_get())
        with self.assertRaises(AccessError):
            order.export_data(['name', 'x_cva_amount_total'])
        with self.assertRaises(AccessError):
            self.env['sale.order'].with_user(user).search(
                [('x_cva_percent', '>', 1)])
        with self.assertRaises(AccessError):
            self.env['sale.cva.history'].with_user(user).search([])
        with self.assertRaises(AccessError):
            self.env['sale.cva.quick.percent'].with_user(user).search([])
        with self.assertRaises(AccessError):
            self.env['sale.cva.apply.wizard'].with_user(user).create({
                'order_id': self.order.id, 'percent': 10.0, 'reason': 'X'})
        with self.assertRaises(AccessError):
            order.action_cva_open_apply_wizard()

    def test_01_salesman_blocked(self):
        self._assert_no_access(self.user_salesman)

    def test_02_general_admin_blocked(self):
        """Criterio 8: el administrador general NO obtiene acceso automático."""
        self._assert_no_access(self.user_sysadmin)

    # ------------------------------------------------------------------
    # Consulta: lee todo, no modifica nada
    # ------------------------------------------------------------------
    def test_03_consulta_read_only(self):
        order = self.order.with_user(self.user_consulta)
        values = order.read(['x_cva_percent', 'x_cva_amount_total'])[0]
        self.assertAlmostEqual(values['x_cva_percent'], 40.0)
        self.assertAlmostEqual(values['x_cva_amount_total'], 60.0)
        self.assertTrue(self.env['sale.cva.history']
                        .with_user(self.user_consulta).search_count([]))
        with self.assertRaises(AccessError):
            order.write({'x_cva_percent': 10.0})
        line = self._product_lines(self.order).with_user(self.user_consulta)
        with self.assertRaises(AccessError):
            line.write({'x_cva_has_override': True,
                        'x_cva_percent_override': 5.0})
        with self.assertRaises(AccessError):
            order._cva_apply(10.0, reason='NO DEBE PASAR')
        with self.assertRaises(AccessError):
            order._cva_reset('NO DEBE PASAR')
        with self.assertRaises(AccessError):
            self.env['sale.cva.quick.percent'].with_user(self.user_consulta) \
                .create({'name': 'X', 'percent': 15.0})

    def test_04_manager_full(self):
        order = self.order.with_user(self.user_manager)
        self.assertAlmostEqual(order.x_cva_amount_total, 60.0)
        self.env['sale.cva.quick.percent'].with_user(self.user_manager) \
            .create({'name': '15%', 'percent': 15.0})
        self._reset(self.order)
        self.assertEqual(self.order.x_cva_state, 'reset')

    # ------------------------------------------------------------------
    # Sin rastro en el chatter
    # ------------------------------------------------------------------
    def test_05_chatter_no_trace(self):
        """Aplicar o restablecer NO publica nada en el chatter de la orden:
        ni con el subtipo CVA ni como nota, para nadie."""
        Message = self.env['mail.message'].sudo()
        base = [('model', '=', 'sale.order'), ('res_id', '=', self.order.id)]
        count_before = Message.search_count(base)
        self._apply(self.order, 20.0, reason='OTRO AJUSTE')
        self._apply(self.order, 30.0, scope='lines',
                    line_ids=self.order.order_line.ids, reason='')
        self._reset(self.order, reason='')
        self.assertEqual(Message.search_count(base), count_before)
        subtype = self.env.ref('sale_admin_value_control.mt_cva')
        self.assertFalse(Message.search_count(
            base + [('subtype_id', '=', subtype.id)]))
        # la purga elimina lo que versiones anteriores hubieran publicado
        legacy = self.order.sudo().message_post(
            body='LEGADO', subtype_xmlid='sale_admin_value_control.mt_cva',
            message_type='comment')
        self.env['sale.order']._cva_purge_chatter()
        self.assertFalse(legacy.exists())
        # los mensajes normales siguen intactos y visibles para el vendedor
        self.order.with_user(self.user_salesman).message_post(
            body='NOTA NORMAL', message_type='comment')
        self.assertTrue(self.env['mail.message']
                        .with_user(self.user_salesman).search_count(base))

    def test_06_multicompany_rules(self):
        """El historial y los porcentajes rápidos respetan la compañía."""
        companies = self.env['res.company'].search([])
        if len(companies) < 2:
            self.skipTest('Se necesitan dos compañías')
        other = (companies - self.company)[0]
        quick = self.env['sale.cva.quick.percent'].sudo().create({
            'name': 'OTRA CIA', 'percent': 33.0, 'company_id': other.id})
        visible = self.env['sale.cva.quick.percent'].with_user(
            self.user_consulta).with_context(
            allowed_company_ids=[self.company.id]).search([])
        self.assertNotIn(quick.id, visible.ids)
