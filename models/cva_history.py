# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .cva_lens import CVA_USER


class SaleCvaHistory(models.Model):
    """Historial inmutable del control de valor administrativo.

    Se crea únicamente desde código (sudo). Ningún grupo tiene create/write/
    unlink en la ACL y, además, write/unlink levantan error incluso para el
    superusuario, salvo el contexto técnico ``cva_history_maintenance``.
    """
    _name = 'sale.cva.history'
    _description = 'Historial de valor administrativo'
    _order = 'date desc, id desc'

    order_id = fields.Many2one(
        'sale.order', string='Orden', required=True, ondelete='cascade',
        index=True, groups=CVA_USER)
    company_id = fields.Many2one(
        related='order_id.company_id', store=True, groups=CVA_USER)
    currency_id = fields.Many2one(
        related='order_id.currency_id', store=True, groups=CVA_USER)
    action = fields.Selection([
        ('apply_order', 'Aplicación general'),
        ('apply_lines', 'Aplicación por línea'),
        ('reset', 'Restablecimiento'),
    ], string='Acción', required=True, groups=CVA_USER)
    user_id = fields.Many2one(
        'res.users', string='Responsable', required=True, groups=CVA_USER)
    date = fields.Datetime(
        string='Fecha y hora', required=True, default=fields.Datetime.now,
        groups=CVA_USER)
    reason = fields.Char(string='Motivo', groups=CVA_USER)
    percent_before = fields.Float(
        string='% anterior', digits=(5, 2), groups=CVA_USER)
    percent_after = fields.Float(
        string='% nuevo', digits=(5, 2), groups=CVA_USER)
    amount_before = fields.Monetary(
        string='Total administrativo anterior', currency_field='currency_id',
        groups=CVA_USER)
    amount_after = fields.Monetary(
        string='Total administrativo resultante', currency_field='currency_id',
        groups=CVA_USER)
    amount_reference = fields.Monetary(
        string='Total registrado', currency_field='currency_id',
        groups=CVA_USER)
    line_ids = fields.One2many(
        'sale.cva.history.line', 'history_id', string='Líneas afectadas',
        groups=CVA_USER)

    def _cva_assert_maintenance(self):
        if not self.env.context.get('cva_history_maintenance'):
            raise UserError(_(
                'El historial del control de valor administrativo es '
                'inalterable: no se puede modificar ni eliminar.'))

    def write(self, vals):
        self._cva_assert_maintenance()
        return super().write(vals)

    def unlink(self):
        self._cva_assert_maintenance()
        return super().unlink()


class SaleCvaHistoryLine(models.Model):
    _name = 'sale.cva.history.line'
    _description = 'Historial de valor administrativo (línea)'
    _order = 'id'

    history_id = fields.Many2one(
        'sale.cva.history', string='Movimiento', required=True,
        ondelete='cascade', index=True, groups=CVA_USER)
    currency_id = fields.Many2one(
        related='history_id.currency_id', groups=CVA_USER)
    line_id = fields.Many2one(
        'sale.order.line', string='Línea', ondelete='set null',
        groups=CVA_USER)
    product_id = fields.Many2one(
        'product.product', string='Producto', groups=CVA_USER)
    name = fields.Char(string='Descripción', groups=CVA_USER)
    qty = fields.Float(string='Cantidad', groups=CVA_USER)
    percent_before = fields.Float(string='% anterior', digits=(5, 2), groups=CVA_USER)
    percent_after = fields.Float(string='% nuevo', digits=(5, 2), groups=CVA_USER)
    price_unit_ref = fields.Float(string='Precio de referencia', groups=CVA_USER)
    price_unit_before = fields.Float(string='Precio adm. anterior', groups=CVA_USER)
    price_unit_after = fields.Float(string='Precio adm. resultante', groups=CVA_USER)
    subtotal_before = fields.Monetary(
        string='Subtotal adm. anterior', currency_field='currency_id', groups=CVA_USER)
    subtotal_after = fields.Monetary(
        string='Subtotal adm. resultante', currency_field='currency_id', groups=CVA_USER)
    total_before = fields.Monetary(
        string='Total adm. anterior', currency_field='currency_id', groups=CVA_USER)
    total_after = fields.Monetary(
        string='Total adm. resultante', currency_field='currency_id', groups=CVA_USER)

    def write(self, vals):
        self.env['sale.cva.history']._cva_assert_maintenance()
        return super().write(vals)

    def unlink(self):
        self.env['sale.cva.history']._cva_assert_maintenance()
        return super().unlink()
