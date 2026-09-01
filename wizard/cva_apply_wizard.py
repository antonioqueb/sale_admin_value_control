# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SaleCvaApplyWizard(models.TransientModel):
    _name = 'sale.cva.apply.wizard'
    _description = 'Aplicar ajuste administrativo'

    order_id = fields.Many2one(
        'sale.order', string='Orden', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='order_id.currency_id')
    company_id = fields.Many2one(related='order_id.company_id')
    scope = fields.Selection([
        ('order', 'Toda la orden'),
        ('lines', 'Sólo líneas seleccionadas'),
    ], string='Alcance', required=True, default='order')
    percent = fields.Float(string='Porcentaje', digits=(5, 2), required=True)
    quick_id = fields.Many2one(
        'sale.cva.quick.percent', string='Porcentaje rápido',
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    keep_line_overrides = fields.Boolean(
        string='Conservar porcentajes particulares de líneas',
        help='Al aplicar el porcentaje general, las líneas que ya tienen un '
             'porcentaje particular lo conservan. Si se deja apagado, los '
             'particulares se limpian y toda la orden queda con el general.')
    reason = fields.Char(string='Motivo', required=True)
    line_ids = fields.One2many(
        'sale.cva.apply.wizard.line', 'wizard_id', string='Líneas')

    total_ref = fields.Monetary(
        string='Total registrado', compute='_compute_preview')
    total_adm_current = fields.Monetary(
        string='Total administrativo actual', compute='_compute_preview')
    total_adm_new = fields.Monetary(
        string='Total administrativo nuevo', compute='_compute_preview')
    diff_new = fields.Monetary(
        string='Diferencia resultante', compute='_compute_preview')

    @api.constrains('percent')
    def _check_percent(self):
        for wiz in self:
            if wiz.percent < 0 or wiz.percent > 100:
                raise ValidationError(_(
                    'El porcentaje debe estar entre 0%% y 100%% '
                    '(capturaste %.2f%%).') % wiz.percent)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        order_id = res.get('order_id') or self.env.context.get('default_order_id')
        if order_id and 'line_ids' in fields_list:
            order = self.env['sale.order'].browse(order_id)
            res['line_ids'] = [(0, 0, {
                'line_id': line.id,
                'selected': True,
            }) for line in order.order_line.filtered(lambda l: not l.display_type)]
            res.setdefault('percent', order.x_cva_percent or 0.0)
        return res

    @api.onchange('quick_id')
    def _onchange_quick_id(self):
        if self.quick_id:
            self.percent = self.quick_id.percent

    def _line_new_percent(self, wline):
        """% que quedaría en la línea al confirmar con la captura actual."""
        self.ensure_one()
        line = wline.line_id
        if self.scope == 'order':
            if self.keep_line_overrides and line.x_cva_has_override:
                return line.x_cva_percent_override or 0.0
            return self.percent
        if wline.selected:
            return self.percent
        return line.x_cva_percent or 0.0

    @api.depends('percent', 'scope', 'keep_line_overrides',
                 'line_ids.selected', 'order_id')
    def _compute_preview(self):
        for wiz in self:
            order = wiz.order_id
            total_ref = order.amount_total or 0.0
            total_new = 0.0
            for wline in wiz.line_ids:
                line = wline.line_id
                pct_new = wiz._line_new_percent(wline)
                total_new += (line.price_total or 0.0) * (1.0 - pct_new / 100.0)
            if order.currency_id:
                total_new = order.currency_id.round(total_new)
            wiz.total_ref = total_ref
            wiz.total_adm_current = order.x_cva_amount_total or 0.0
            wiz.total_adm_new = total_new
            wiz.diff_new = total_ref - total_new

    def action_confirm(self):
        self.ensure_one()
        order = self.order_id
        if self.scope == 'lines':
            selected = self.line_ids.filtered('selected').mapped('line_id')
            if not selected:
                raise UserError(_('Selecciona al menos una línea.'))
            order._cva_apply(self.percent, scope='lines',
                             line_ids=selected.ids, reason=self.reason)
        else:
            order._cva_apply(self.percent, scope='order', reason=self.reason,
                             keep_line_overrides=self.keep_line_overrides)
        return {'type': 'ir.actions.act_window_close'}


class SaleCvaApplyWizardLine(models.TransientModel):
    _name = 'sale.cva.apply.wizard.line'
    _description = 'Aplicar ajuste administrativo (línea)'

    wizard_id = fields.Many2one(
        'sale.cva.apply.wizard', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    selected = fields.Boolean(string='Aplicar', default=True)
    line_id = fields.Many2one(
        'sale.order.line', string='Línea', required=True, ondelete='cascade')
    product_id = fields.Many2one(related='line_id.product_id')
    name = fields.Text(related='line_id.name', string='Descripción')
    qty = fields.Float(related='line_id.product_uom_qty', string='Cantidad')
    price_unit_ref = fields.Float(
        related='line_id.x_cva_price_unit_ref', string='Precio referencia')
    percent_current = fields.Float(
        related='line_id.x_cva_percent', string='% actual')
    has_override = fields.Boolean(
        related='line_id.x_cva_has_override', string='Particular')
    subtotal_adm_current = fields.Monetary(
        related='line_id.x_cva_price_subtotal', string='Subtotal adm. actual')
    percent_new = fields.Float(
        string='% nuevo', compute='_compute_preview_line', digits=(5, 2))
    subtotal_adm_new = fields.Monetary(
        string='Subtotal adm. nuevo', compute='_compute_preview_line')

    @api.depends('selected', 'wizard_id.percent', 'wizard_id.scope',
                 'wizard_id.keep_line_overrides')
    def _compute_preview_line(self):
        for wline in self:
            wiz = wline.wizard_id
            if not wiz or not wline.line_id:
                wline.percent_new = 0.0
                wline.subtotal_adm_new = 0.0
                continue
            pct = wiz._line_new_percent(wline)
            wline.percent_new = pct
            wline.subtotal_adm_new = (wline.line_id.price_subtotal or 0.0) * (1.0 - pct / 100.0)
