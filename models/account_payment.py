# -*- coding: utf-8 -*-
"""Valor administrativo de los pagos: el pago conserva SIEMPRE su importe
real; el importe administrativo descuenta la porción ajustada de las facturas
con las que está conciliado. Es sólo un indicador de presentación."""
import logging

from odoo import api, fields, models

from .cva_lens import CVA_USER, CUSTOMER_MOVE_TYPES

_logger = logging.getLogger(__name__)


class AccountPayment(models.Model):
    _name = 'account.payment'
    _inherit = ['account.payment', 'sale.cva.lens.mixin']

    x_cva_amount = fields.Monetary(
        string='Importe administrativo', copy=False,
        compute='_compute_x_cva_amount', store=True, groups=CVA_USER,
        help='Importe del pago ajustado por la proporción administrativa de '
             'las facturas conciliadas. El importe real del pago no cambia.')

    @api.depends('amount', 'currency_id', 'partner_type', 'payment_type',
                 'invoice_ids')
    def _compute_x_cva_amount(self):
        for pay in self:
            pay.x_cva_amount = pay._cva_amount_value()

    def _cva_amount_value(self):
        self.ensure_one()
        amount = self.amount or 0.0
        if self.partner_type != 'customer' or not amount:
            return amount
        move = self.move_id
        if move:
            lines = move.line_ids.filtered(
                lambda l: l.account_id.account_type in
                ('asset_receivable', 'liability_payable'))
            partials = lines.matched_debit_ids | lines.matched_credit_ids
            if partials:
                adjustment = 0.0
                for partial in partials:
                    if partial.debit_move_id in lines:
                        other = partial.credit_move_id
                        matched = partial.debit_amount_currency
                    else:
                        other = partial.debit_move_id
                        matched = partial.credit_amount_currency
                    other_move = other.move_id.sudo()
                    if other_move.move_type in CUSTOMER_MOVE_TYPES and other_move.amount_total:
                        ratio = (other_move.x_cva_amount_total or 0.0) / other_move.amount_total
                        adjustment += (matched or 0.0) * (1.0 - ratio)
                return amount - adjustment
        # Odoo 19: los pagos pueden nacer 'in_process' SIN asiento, ligados a
        # sus facturas vía invoice_ids; el administrativo sale de ese vínculo.
        invoices = self.env['account.move']
        if 'invoice_ids' in self._fields:
            invoices = self.sudo().invoice_ids
        if not invoices:
            invoices = self.sudo().reconciled_invoice_ids
        invoices = invoices.filtered(
            lambda m: m.move_type in CUSTOMER_MOVE_TYPES)
        if invoices:
            total = sum(invoices.mapped('amount_total'))
            adm = sum(invoices.mapped('x_cva_amount_total'))
            return amount * (adm / total) if total else amount
        return amount

    def _cva_lens_map(self):
        def _company_scaled(pay):
            amount = pay.amount or 0.0
            factor = (pay.x_cva_amount / amount) if amount else 1.0
            return (pay.amount_company_currency_signed or 0.0) * factor

        def _signed(pay):
            amount = pay.amount or 0.0
            factor = (pay.x_cva_amount / amount) if amount else 1.0
            return (pay.amount_signed or 0.0) * factor

        return {
            'amount': 'x_cva_amount',
            'amount_signed': _signed,
            'amount_company_currency_signed': _company_scaled,
        }


class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    def _cva_related_payments(self):
        lines = self.debit_move_id | self.credit_move_id
        payments = lines.payment_id
        try:
            payments |= lines.move_id.origin_payment_id
        except Exception:  # noqa: BLE001 - campo según build
            pass
        return payments

    @api.model_create_multi
    def create(self, vals_list):
        partials = super().create(vals_list)
        try:
            payments = partials._cva_related_payments()
            if payments:
                payments.sudo().modified(['amount'])
        except Exception:  # noqa: BLE001
            _logger.exception('[CVA] no se recalculó el importe administrativo de pagos')
        return partials

    def unlink(self):
        try:
            payments = self._cva_related_payments()
        except Exception:  # noqa: BLE001
            payments = self.env['account.payment']
        res = super().unlink()
        try:
            if payments.exists():
                payments.sudo().modified(['amount'])
        except Exception:  # noqa: BLE001
            _logger.exception('[CVA] no se recalculó el importe administrativo de pagos')
        return res
