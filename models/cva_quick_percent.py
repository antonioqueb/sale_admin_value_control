# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .cva_lens import CVA_USER


class SaleCvaQuickPercent(models.Model):
    """Porcentajes rápidos configurables del asistente de aplicación."""
    _name = 'sale.cva.quick.percent'
    _description = 'Porcentaje rápido de valor administrativo'
    _order = 'sequence, percent, id'

    name = fields.Char(string='Etiqueta', required=True, groups=CVA_USER)
    percent = fields.Float(
        string='Porcentaje', digits=(5, 2), required=True, groups=CVA_USER)
    sequence = fields.Integer(default=10, groups=CVA_USER)
    active = fields.Boolean(default=True, groups=CVA_USER)
    company_id = fields.Many2one(
        'res.company', string='Compañía', groups=CVA_USER,
        help='Vacío = compartido entre compañías.')

    @api.constrains('percent')
    def _check_percent(self):
        for rec in self:
            if rec.percent < 0 or rec.percent > 100:
                raise ValidationError(_(
                    'El porcentaje rápido debe estar entre 0%% y 100%% '
                    '(capturaste %.2f%%).') % rec.percent)
