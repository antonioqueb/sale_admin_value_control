# -*- coding: utf-8 -*-
"""Columnas administrativas en los análisis SQL nativos (sale.report y
account.invoice.report) + lente sobre sus medidas. Los análisis nativos no
se alteran para nadie más: las columnas nuevas sólo son visibles para los
grupos CVA y la sustitución de medidas sólo aplica con la lente."""
from odoo import fields, models
from odoo.tools import SQL

from .cva_lens import CVA_USER


class SaleReport(models.Model):
    _name = 'sale.report'
    _inherit = ['sale.report', 'sale.cva.lens.mixin']

    x_cva_price_subtotal = fields.Monetary(
        string='Subtotal administrativo', readonly=True, groups=CVA_USER)
    x_cva_price_total = fields.Monetary(
        string='Total administrativo', readonly=True, groups=CVA_USER)
    x_cva_amount_diff = fields.Monetary(
        string='Diferencia administrativa', readonly=True, groups=CVA_USER)
    x_cva_percent = fields.Float(
        string='% administrativo', readonly=True, aggregator='avg',
        groups=CVA_USER)

    def _select_additional_fields(self):
        res = super()._select_additional_fields()
        rate_order = self._case_value_or_one('s.currency_rate')
        rate_table = self._case_value_or_one('account_currency_table.rate')
        res['x_cva_price_subtotal'] = f"""
            CASE WHEN l.product_id IS NOT NULL THEN SUM(
                COALESCE(l.x_cva_price_subtotal, l.price_subtotal)
                / {rate_order} * {rate_table}) ELSE 0 END"""
        res['x_cva_price_total'] = f"""
            CASE WHEN l.product_id IS NOT NULL THEN SUM(
                COALESCE(l.x_cva_price_total, l.price_total)
                / {rate_order} * {rate_table}) ELSE 0 END"""
        res['x_cva_amount_diff'] = f"""
            CASE WHEN l.product_id IS NOT NULL THEN SUM(
                (l.price_subtotal - COALESCE(l.x_cva_price_subtotal, l.price_subtotal))
                / {rate_order} * {rate_table}) ELSE 0 END"""
        res['x_cva_percent'] = "AVG(COALESCE(l.x_cva_percent, 0))"
        return res

    def _cva_lens_map(self):
        return {
            'price_subtotal': 'x_cva_price_subtotal',
            'price_total': 'x_cva_price_total',
        }


class AccountInvoiceReport(models.Model):
    _name = 'account.invoice.report'
    _inherit = ['account.invoice.report', 'sale.cva.lens.mixin']

    x_cva_price_subtotal = fields.Float(
        string='Base administrativa', readonly=True, groups=CVA_USER)
    x_cva_price_subtotal_currency = fields.Float(
        string='Base administrativa (divisa)', readonly=True, groups=CVA_USER)
    x_cva_price_total = fields.Float(
        string='Total administrativo', readonly=True, groups=CVA_USER)
    x_cva_price_total_currency = fields.Float(
        string='Total administrativo (divisa)', readonly=True, groups=CVA_USER)

    def _select(self) -> SQL:
        return SQL(
            '%s, %s',
            super()._select(),
            SQL('''
                line.price_subtotal * (1 - COALESCE(line.x_cva_percent, 0) / 100.0)
                    * (CASE WHEN move.move_type IN ('in_invoice','out_refund','in_receipt') THEN -1 ELSE 1 END)
                                                    AS x_cva_price_subtotal_currency,
                -line.balance * (1 - COALESCE(line.x_cva_percent, 0) / 100.0)
                    * account_currency_table.rate   AS x_cva_price_subtotal,
                line.price_total * (1 - COALESCE(line.x_cva_percent, 0) / 100.0)
                    * (CASE WHEN move.move_type IN ('in_invoice','out_refund','in_receipt') THEN -1 ELSE 1 END)
                    / move.invoice_currency_rate    AS x_cva_price_total,
                line.price_total * (1 - COALESCE(line.x_cva_percent, 0) / 100.0)
                    * (CASE WHEN move.move_type IN ('in_invoice','out_refund','in_receipt') THEN -1 ELSE 1 END)
                                                    AS x_cva_price_total_currency
            '''),
        )

    def _cva_lens_map(self):
        return {
            'price_subtotal': 'x_cva_price_subtotal',
            'price_subtotal_currency': 'x_cva_price_subtotal_currency',
            'price_total': 'x_cva_price_total',
            'price_total_currency': 'x_cva_price_total_currency',
        }
