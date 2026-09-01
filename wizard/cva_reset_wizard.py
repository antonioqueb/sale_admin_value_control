# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class SaleCvaResetWizard(models.TransientModel):
    _name = 'sale.cva.reset.wizard'
    _description = 'Restablecer valor administrativo'

    order_id = fields.Many2one(
        'sale.order', string='Orden', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='order_id.currency_id')
    reason = fields.Char(string='Motivo', required=True)
    summary = fields.Text(
        string='Resumen', compute='_compute_summary')

    @api.depends('order_id')
    def _compute_summary(self):
        for wiz in self:
            order = wiz.order_id
            if not order:
                wiz.summary = ''
                continue
            overrides = order.order_line.filtered('x_cva_has_override')
            wiz.summary = _(
                'Orden %(order)s · %% general actual: %(pct).2f%% · '
                'líneas con %% particular: %(lines)d\n'
                'Total registrado: %(ref).2f · Total administrativo actual: %(adm).2f\n\n'
                'Al confirmar, el porcentaje general vuelve a 0%%, los '
                'porcentajes particulares se limpian y los valores '
                'administrativos quedan iguales a los registrados. El '
                'historial anterior se conserva.') % {
                    'order': order.name,
                    'pct': order.x_cva_percent or 0.0,
                    'lines': len(overrides),
                    'ref': order.amount_total or 0.0,
                    'adm': order.x_cva_amount_total or 0.0,
                }

    def action_confirm(self):
        self.ensure_one()
        self.order_id._cva_reset(self.reason)
        return {'type': 'ir.actions.act_window_close'}
