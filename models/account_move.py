# -*- coding: utf-8 -*-
"""Valores administrativos en facturas de cliente.

Cada línea de factura hereda el % administrativo de su línea de venta (o de
la orden de origen); la factura suma los importes ajustados. Nada de esto
escribe sobre los campos contables: son columnas paralelas que la lente usa
para presentar y los indicadores para comparar.
"""
import logging

from odoo import api, fields, models

from .cva_lens import CVA_USER, CUSTOMER_MOVE_TYPES

_logger = logging.getLogger(__name__)


class AccountMoveLine(models.Model):
    _name = 'account.move.line'
    _inherit = ['account.move.line', 'sale.cva.lens.mixin']

    x_cva_percent = fields.Float(
        string='% administrativo', digits=(5, 2), copy=False,
        compute='_compute_x_cva_values', store=True, groups=CVA_USER)
    x_cva_price_unit_gross = fields.Float(
        string='Precio unitario administrativo', digits='Product Price',
        copy=False, compute='_compute_x_cva_values', store=True,
        groups=CVA_USER)
    x_cva_price_subtotal = fields.Monetary(
        string='Subtotal administrativo', currency_field='currency_id',
        copy=False, compute='_compute_x_cva_values', store=True,
        groups=CVA_USER)
    x_cva_price_total = fields.Monetary(
        string='Total administrativo', currency_field='currency_id',
        copy=False, compute='_compute_x_cva_values', store=True,
        groups=CVA_USER)

    def _cva_percent_value(self):
        self.ensure_one()
        move = self.move_id
        if move.move_type not in CUSTOMER_MOVE_TYPES or self.display_type != 'product':
            return 0.0
        sale_lines = self.sale_line_ids
        if sale_lines:
            if len(sale_lines) == 1:
                return sale_lines.x_cva_percent or 0.0
            total_qty = sum(sale_lines.mapped('product_uom_qty'))
            if not total_qty:
                return sale_lines[0].x_cva_percent or 0.0
            return sum((sl.x_cva_percent or 0.0) * sl.product_uom_qty
                       for sl in sale_lines) / total_qty
        orders = move.line_ids.sale_line_ids.order_id
        if len(orders) == 1 and orders.x_cva_active:
            return orders.x_cva_percent or 0.0
        return 0.0

    @api.depends('price_unit', 'discount', 'quantity', 'tax_ids', 'currency_id',
                 'display_type', 'move_id.move_type',
                 'sale_line_ids.x_cva_percent',
                 'sale_line_ids.order_id.x_cva_active')
    def _compute_x_cva_values(self):
        AccountTax = self.env['account.tax']
        for line in self:
            pct = line._cva_percent_value()
            factor = 1.0 - pct / 100.0
            line.x_cva_percent = pct
            line.x_cva_price_unit_gross = (line.price_unit or 0.0) * factor
            if line.display_type != 'product':
                line.x_cva_price_subtotal = 0.0
                line.x_cva_price_total = 0.0
                continue
            if not pct:
                line.x_cva_price_subtotal = line.price_subtotal
                line.x_cva_price_total = line.price_total
                continue
            company = line.company_id or self.env.company
            try:
                base_line = line._prepare_base_line_for_taxes_computation(
                    price_unit=(line.price_unit or 0.0) * factor)
                AccountTax._add_tax_details_in_base_line(base_line, company)
                AccountTax._round_base_lines_tax_details([base_line], company)
                details = base_line['tax_details']
                line.x_cva_price_subtotal = details['total_excluded_currency']
                line.x_cva_price_total = details['total_included_currency']
            except Exception:  # noqa: BLE001 - respaldo proporcional
                _logger.exception('[CVA] motor fiscal falló en apunte %s', line.id)
                line.x_cva_price_subtotal = (line.price_subtotal or 0.0) * factor
                line.x_cva_price_total = (line.price_total or 0.0) * factor

    def _cva_line_factor(self):
        """Factor de la línea: (1−%) para líneas de producto; proporción de la
        factura para impuestos, cuenta por cobrar y demás apuntes."""
        self.ensure_one()
        move = self.move_id
        if move.move_type not in CUSTOMER_MOVE_TYPES:
            return 1.0
        if self.display_type == 'product':
            return 1.0 - (self.x_cva_percent or 0.0) / 100.0
        return move._cva_ratio()

    def _cva_lens_map(self):
        def _scaled(name):
            return lambda l: (l[name] or 0.0) * l._cva_line_factor()

        return {
            'price_unit': 'x_cva_price_unit_gross',
            'price_subtotal': 'x_cva_price_subtotal',
            'price_total': 'x_cva_price_total',
            'debit': _scaled('debit'),
            'credit': _scaled('credit'),
            'balance': _scaled('balance'),
            'amount_currency': _scaled('amount_currency'),
            'amount_residual': _scaled('amount_residual'),
            'amount_residual_currency': _scaled('amount_residual_currency'),
        }


class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'sale.cva.lens.mixin']

    x_cva_amount_untaxed = fields.Monetary(
        string='Base administrativa', copy=False,
        compute='_compute_x_cva_amounts', store=True, groups=CVA_USER)
    x_cva_amount_tax = fields.Monetary(
        string='Impuestos administrativos', copy=False,
        compute='_compute_x_cva_amounts', store=True, groups=CVA_USER)
    x_cva_amount_total = fields.Monetary(
        string='Total administrativo', copy=False,
        compute='_compute_x_cva_amounts', store=True, groups=CVA_USER)
    x_cva_amount_residual = fields.Monetary(
        string='Adeudo administrativo', copy=False,
        compute='_compute_x_cva_amounts', store=True, groups=CVA_USER)

    @api.depends('line_ids.x_cva_price_subtotal', 'line_ids.x_cva_price_total',
                 'amount_untaxed', 'amount_tax', 'amount_total',
                 'amount_residual', 'move_type')
    def _compute_x_cva_amounts(self):
        for move in self:
            if move.move_type in CUSTOMER_MOVE_TYPES:
                product_lines = move.line_ids.filtered(
                    lambda l: l.display_type == 'product')
                untaxed = sum(product_lines.mapped('x_cva_price_subtotal'))
                total = sum(product_lines.mapped('x_cva_price_total'))
                currency = move.currency_id
                if currency:
                    untaxed = currency.round(untaxed)
                    total = currency.round(total)
            else:
                untaxed, total = move.amount_untaxed, move.amount_total
            move.x_cva_amount_untaxed = untaxed
            move.x_cva_amount_total = total
            move.x_cva_amount_tax = total - untaxed
            ratio = (total / move.amount_total) if move.amount_total else 1.0
            move.x_cva_amount_residual = (move.amount_residual or 0.0) * ratio

    def _cva_ratio(self):
        self.ensure_one()
        if self.amount_total:
            return (self.x_cva_amount_total or 0.0) / self.amount_total
        return 1.0

    def _cva_tax_totals(self):
        self.ensure_one()
        if self.move_type not in CUSTOMER_MOVE_TYPES:
            return self.tax_totals
        AccountTax = self.env['account.tax']
        lines = self.line_ids.filtered(lambda l: l.display_type == 'product')
        base_lines = []
        for line in lines:
            factor = 1.0 - (line.x_cva_percent or 0.0) / 100.0
            base_lines.append(line._prepare_base_line_for_taxes_computation(
                price_unit=(line.price_unit or 0.0) * factor))
        AccountTax._add_tax_details_in_base_lines(base_lines, self.company_id)
        AccountTax._round_base_lines_tax_details(base_lines, self.company_id)
        return AccountTax._get_tax_totals_summary(
            base_lines=base_lines,
            currency=self.currency_id or self.company_id.currency_id,
            company=self.company_id,
        )

    def _cva_lens_map(self):
        def _scaled(name):
            return lambda m: (m[name] or 0.0) * m._cva_ratio()

        m = {
            'amount_untaxed': 'x_cva_amount_untaxed',
            'amount_tax': 'x_cva_amount_tax',
            'amount_total': 'x_cva_amount_total',
            'amount_residual': 'x_cva_amount_residual',
            'tax_totals': lambda mv: mv._cva_tax_totals(),
        }
        for opt in ('amount_untaxed_signed', 'amount_untaxed_in_currency_signed',
                    'amount_tax_signed', 'amount_total_signed',
                    'amount_total_in_currency_signed', 'amount_residual_signed'):
            if opt in self._fields:
                m[opt] = _scaled(opt)
        return m

    def action_cva_print_invoice(self):
        """Impresión administrativa de la factura: usa la plantilla estándar a
        través de la ruta interactiva /report/, que es la única donde la lente
        aplica. El PDF legal (Enviar e imprimir) sigue saliendo real."""
        self.ensure_one()
        return self.env.ref('account.account_invoices').report_action(self)
