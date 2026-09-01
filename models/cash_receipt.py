# -*- coding: utf-8 -*-
"""Lente sobre el recibo de efectivo: el recibo conserva su importe real; el
usuario con la lente lo ve (en pantalla y en el impreso) ajustado por la
proporción administrativa de sus pedidos asociados."""
from odoo import models


class CashReceipt(models.Model):
    _name = 'cash.receipt'
    _inherit = ['cash.receipt', 'sale.cva.lens.mixin']

    def _cva_ratio(self):
        self.ensure_one()
        orders = self.sudo().sale_order_ids
        if not orders:
            return 1.0
        total = sum(orders.mapped('amount_total'))
        if not total:
            return 1.0
        return sum(orders.mapped('x_cva_amount_total')) / total

    def _cva_lens_map(self):
        def _scaled(name):
            return lambda r: (r[name] or 0.0) * r._cva_ratio()

        def _orders_adm(receipt):
            return sum(receipt.sudo().sale_order_ids.mapped('x_cva_amount_total'))

        m = {
            'amount': _scaled('amount'),
            'total_orders_amount': _orders_adm,
        }
        for opt in ('amount_mxn', 'pending_amount'):
            if opt in self._fields:
                m[opt] = _scaled(opt)
        return m
