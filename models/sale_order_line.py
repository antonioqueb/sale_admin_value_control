# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .cva_lens import CVA_USER

_logger = logging.getLogger(__name__)


class SaleOrderLine(models.Model):
    _name = 'sale.order.line'
    _inherit = ['sale.order.line', 'sale.cva.lens.mixin']

    # ------------------------------------------------------------------
    # Campos administrativos (independientes de los nativos; jamás se
    # escribe el resultado en price_unit/discount/price_subtotal/...)
    # ------------------------------------------------------------------
    x_cva_has_override = fields.Boolean(
        string='Con % particular', copy=False, groups=CVA_USER)
    x_cva_percent_override = fields.Float(
        string='% particular', digits=(5, 2), copy=False, groups=CVA_USER)
    x_cva_percent = fields.Float(
        string='% administrativo', digits=(5, 2), copy=False,
        compute='_compute_x_cva_values', store=True, groups=CVA_USER)
    x_cva_percent_inherited = fields.Boolean(
        string='Heredado de la orden', copy=False,
        compute='_compute_x_cva_values', store=True, groups=CVA_USER)
    x_cva_price_unit_ref = fields.Float(
        string='Precio unitario de referencia', digits='Product Price',
        copy=False, compute='_compute_x_cva_values', store=True,
        groups=CVA_USER,
        help='Precio neto registrado: precio unitario menos el descuento '
             'comercial. Es la base del cálculo administrativo.')
    x_cva_price_unit = fields.Float(
        string='Precio unitario administrativo', digits='Product Price',
        copy=False, compute='_compute_x_cva_values', store=True,
        groups=CVA_USER)
    x_cva_price_unit_gross = fields.Float(
        string='Precio unitario administrativo (bruto)',
        digits='Product Price', copy=False,
        compute='_compute_x_cva_values', store=True, groups=CVA_USER,
        help='Precio unitario × (1 − % administrativo), antes del descuento '
             'comercial. Es lo que la lente muestra en la columna de precio.')
    x_cva_price_subtotal = fields.Monetary(
        string='Subtotal administrativo', copy=False,
        compute='_compute_x_cva_values', store=True, groups=CVA_USER)
    x_cva_price_tax = fields.Monetary(
        string='Impuestos administrativos', copy=False,
        compute='_compute_x_cva_values', store=True, groups=CVA_USER)
    x_cva_price_total = fields.Monetary(
        string='Total administrativo', copy=False,
        compute='_compute_x_cva_values', store=True, groups=CVA_USER)
    x_cva_write_uid = fields.Many2one(
        'res.users', string='Última modificación adm. por', copy=False,
        groups=CVA_USER)
    x_cva_write_date = fields.Datetime(
        string='Última modificación adm.', copy=False, groups=CVA_USER)

    _CVA_MANUAL_FIELDS = ('x_cva_has_override', 'x_cva_percent_override',
                          'x_cva_write_uid', 'x_cva_write_date')

    def write(self, vals):
        if any(f in vals for f in self._CVA_MANUAL_FIELDS):
            self.env['sale.order']._cva_check_manager()
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        if any(f in vals for vals in vals_list for f in self._CVA_MANUAL_FIELDS):
            self.env['sale.order']._cva_check_manager()
        return super().create(vals_list)

    @api.constrains('x_cva_percent_override')
    def _check_x_cva_percent_override(self):
        for line in self:
            if line.x_cva_percent_override < 0 or line.x_cva_percent_override > 100:
                raise ValidationError(_(
                    'El porcentaje administrativo de la línea debe estar '
                    'entre 0%% y 100%% (capturaste %.2f%%).')
                    % line.x_cva_percent_override)

    # ------------------------------------------------------------------
    # Cálculo (mismo motor fiscal que los importes nativos)
    # ------------------------------------------------------------------
    def _cva_effective_percent(self):
        self.ensure_one()
        if self.x_cva_has_override:
            return self.x_cva_percent_override or 0.0
        return self.order_id.x_cva_percent or 0.0

    def _cva_taxed_amounts(self, factor):
        """(subtotal, total) administrativos en la moneda de la orden, con el
        mismo motor de impuestos que usa Odoo para los importes nativos."""
        self.ensure_one()
        AccountTax = self.env['account.tax']
        company = self.order_id.company_id or self.env.company
        price_unit = (self.price_unit or 0.0) * factor
        try:
            base_line = self._prepare_base_line_for_taxes_computation(price_unit=price_unit)
            AccountTax._add_tax_details_in_base_line(base_line, company)
            AccountTax._round_base_lines_tax_details([base_line], company)
            details = base_line['tax_details']
            return details['total_excluded_currency'], details['total_included_currency']
        except Exception:  # noqa: BLE001 - respaldo con compute_all
            _logger.exception('[CVA] motor fiscal nuevo falló en línea %s; uso compute_all', self.id)
            currency = self.currency_id or company.currency_id
            price = price_unit * (1.0 - (self.discount or 0.0) / 100.0)
            taxes = self.tax_ids.compute_all(
                price, currency, self.product_uom_qty or 0.0,
                product=self.product_id, partner=self.order_id.partner_id)
            return taxes['total_excluded'], taxes['total_included']

    @api.depends('price_unit', 'discount', 'product_uom_qty', 'product_uom_id',
                 'tax_ids', 'currency_id', 'display_type', 'company_id',
                 'x_cva_has_override', 'x_cva_percent_override',
                 'order_id.x_cva_percent', 'order_id.x_cva_active')
    def _compute_x_cva_values(self):
        for line in self:
            pct = line._cva_effective_percent()
            factor = 1.0 - pct / 100.0
            line.x_cva_percent = pct
            line.x_cva_percent_inherited = not line.x_cva_has_override
            ref_unit = (line.price_unit or 0.0) * (1.0 - (line.discount or 0.0) / 100.0)
            line.x_cva_price_unit_ref = ref_unit
            line.x_cva_price_unit = ref_unit * factor
            line.x_cva_price_unit_gross = (line.price_unit or 0.0) * factor
            if line.display_type:
                line.x_cva_price_subtotal = 0.0
                line.x_cva_price_tax = 0.0
                line.x_cva_price_total = 0.0
                continue
            subtotal, total = line._cva_taxed_amounts(factor)
            line.x_cva_price_subtotal = subtotal
            line.x_cva_price_total = total
            line.x_cva_price_tax = total - subtotal

    # ------------------------------------------------------------------
    # Lente administrativa
    # ------------------------------------------------------------------
    def _cva_lens_map(self):
        def _factor(line):
            return 1.0 - (line.x_cva_percent or 0.0) / 100.0

        def _per_qty(line, source):
            qty = line.product_uom_qty
            return (line[source] / qty) if qty else 0.0

        m = {
            'price_unit': 'x_cva_price_unit_gross',
            'price_subtotal': 'x_cva_price_subtotal',
            'price_tax': 'x_cva_price_tax',
            'price_total': 'x_cva_price_total',
            'price_reduce_taxexcl': lambda l: _per_qty(l, 'x_cva_price_subtotal'),
            'price_reduce_taxinc': lambda l: _per_qty(l, 'x_cva_price_total'),
        }
        for opt in ('untaxed_amount_invoiced', 'untaxed_amount_to_invoice',
                    'amount_invoiced', 'amount_to_invoice'):
            if opt in self._fields:
                m[opt] = (lambda name: lambda l: (l[name] or 0.0) * _factor(l))(opt)
        return m
