# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, new_test_user


class CvaCase(TransactionCase):
    """Base: producto de servicio (sin inventario ni lotes, para no disparar
    los flujos de placas de los módulos SOM), cliente y cuatro perfiles."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(
            cls.env.context, tracking_disable=True,
            mail_create_nolog=True, mail_notrack=True, no_reset_password=True))
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.partner = cls.env['res.partner'].create({'name': 'CLIENTE CVA TEST'})
        cls.service = cls.env['product.product'].create({
            'name': 'SERVICIO CVA TEST',
            'type': 'service',
            'invoice_policy': 'order',
            'list_price': 100.0,
        })
        # La BD de QA asigna el IVA por defecto de la compañía al producto;
        # las pruebas controlan los impuestos por línea, así que se limpia.
        cls.service.taxes_id = [(5, 0, 0)]
        cls.tax16 = cls.env['account.tax'].create({
            'name': 'IVA 16 CVA TEST',
            'amount': 16.0,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
            'company_id': cls.company.id,
        })
        base_groups = ('sales_team.group_sale_salesman_all_leads,'
                       'account.group_account_invoice,base.group_allow_export')
        cls.user_salesman = new_test_user(
            cls.env, 'cva_test_salesman', groups=base_groups)
        cls.user_sysadmin = new_test_user(
            cls.env, 'cva_test_sysadmin',
            groups=base_groups + ',base.group_system')
        cls.user_consulta = new_test_user(
            cls.env, 'cva_test_consulta',
            groups=base_groups + ',sale_admin_value_control.group_cva_user')
        cls.user_manager = new_test_user(
            cls.env, 'cva_test_manager',
            groups=base_groups + ',sale_admin_value_control.group_cva_manager')

    def _make_order(self, price=100.0, qty=1.0, discount=0.0, taxes=None,
                    n_lines=1, with_section=False):
        lines = []
        if with_section:
            lines.append((0, 0, {'display_type': 'line_section',
                                 'name': 'SECCIÓN DE PRUEBA'}))
        for _i in range(n_lines):
            lines.append((0, 0, {
                'product_id': self.service.id,
                'product_uom_qty': qty,
                'price_unit': price,
                'discount': discount,
                'tax_ids': [(6, 0, taxes.ids if taxes else [])],
            }))
        return self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'user_id': self.user_salesman.id,
            'order_line': lines,
        })

    def _apply(self, order, percent, scope='order', line_ids=None,
               reason='PRUEBA AUTOMÁTICA', **kw):
        return order.with_user(self.user_manager)._cva_apply(
            percent, scope=scope, line_ids=line_ids, reason=reason, **kw)

    def _reset(self, order, reason='RESTABLECER PRUEBA'):
        return order.with_user(self.user_manager)._cva_reset(reason)

    def _product_lines(self, order):
        return order.order_line.filtered(lambda l: not l.display_type)
