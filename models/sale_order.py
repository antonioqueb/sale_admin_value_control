# -*- coding: utf-8 -*-
import logging

from markupsafe import Markup, escape

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .cva_lens import CVA_MANAGER, CVA_USER
from .cva_proxy import CvaMethod

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'sale.cva.lens.mixin']

    # ------------------------------------------------------------------
    # Campos administrativos de cabecera
    # ------------------------------------------------------------------
    x_cva_active = fields.Boolean(
        string='Control administrativo activo', copy=False, groups=CVA_USER)
    x_cva_percent = fields.Float(
        string='% administrativo general', digits=(5, 2), copy=False,
        groups=CVA_USER)
    x_cva_state = fields.Selection([
        ('none', 'Sin ajuste'),
        ('applied', 'Aplicado'),
        ('reset', 'Restablecido'),
    ], string='Estado administrativo', default='none', copy=False,
        groups=CVA_USER)
    x_cva_user_id = fields.Many2one(
        'res.users', string='Responsable del ajuste', copy=False,
        groups=CVA_USER)
    x_cva_date = fields.Datetime(
        string='Fecha del último ajuste', copy=False, groups=CVA_USER)
    x_cva_reason = fields.Char(
        string='Motivo / referencia interna', copy=False, groups=CVA_USER)
    x_cva_amount_untaxed = fields.Monetary(
        string='Base administrativa', copy=False,
        compute='_compute_x_cva_amounts', store=True, groups=CVA_USER)
    x_cva_amount_tax = fields.Monetary(
        string='Impuestos administrativos', copy=False,
        compute='_compute_x_cva_amounts', store=True, groups=CVA_USER)
    x_cva_amount_total = fields.Monetary(
        string='Total administrativo', copy=False,
        compute='_compute_x_cva_amounts', store=True, groups=CVA_USER)
    x_cva_amount_diff = fields.Monetary(
        string='Diferencia administrativa', copy=False,
        compute='_compute_x_cva_amounts', store=True, groups=CVA_USER,
        help='Total registrado menos total administrativo. Es un indicador '
             'interno: jamás genera saldos, créditos ni movimientos contables.')
    x_cva_paid_amount = fields.Monetary(
        string='Pago registrado', compute='_compute_x_cva_payment_info',
        compute_sudo=True, groups=CVA_USER)
    x_cva_paid_amount_adm = fields.Monetary(
        string='Pago administrativo', compute='_compute_x_cva_payment_info',
        compute_sudo=True, groups=CVA_USER)
    x_cva_balance_adm = fields.Monetary(
        string='Saldo administrativo', compute='_compute_x_cva_payment_info',
        compute_sudo=True, groups=CVA_USER,
        help='Total administrativo menos pago administrativo. Indicador '
             'interno, no genera cobranza.')
    x_cva_payments_html = fields.Html(
        string='Pagos (comparativa)', compute='_compute_x_cva_payment_info',
        compute_sudo=True, sanitize=False, groups=CVA_USER)
    x_cva_line_ids = fields.One2many(
        'sale.order.line', 'order_id', string='Líneas (comparativa)',
        domain=[('display_type', '=', False)], groups=CVA_USER)
    x_cva_history_ids = fields.One2many(
        'sale.cva.history', 'order_id', string='Historial administrativo',
        groups=CVA_USER)
    x_cva_history_count = fields.Integer(
        compute='_compute_x_cva_history_count', groups=CVA_USER)

    @api.constrains('x_cva_percent')
    def _check_x_cva_percent(self):
        for order in self:
            if order.x_cva_percent < 0 or order.x_cva_percent > 100:
                raise ValidationError(_(
                    'El porcentaje administrativo debe estar entre 0%% y '
                    '100%% (capturaste %.2f%%).') % order.x_cva_percent)

    # ------------------------------------------------------------------
    # Cálculos
    # ------------------------------------------------------------------
    @api.depends('order_line.x_cva_price_subtotal', 'order_line.x_cva_price_tax',
                 'order_line.x_cva_price_total', 'order_line.display_type',
                 'amount_total')
    def _compute_x_cva_amounts(self):
        for order in self:
            lines = order.order_line.filtered(lambda l: not l.display_type)
            untaxed = sum(lines.mapped('x_cva_price_subtotal'))
            tax = sum(lines.mapped('x_cva_price_tax'))
            total = sum(lines.mapped('x_cva_price_total'))
            currency = order.currency_id
            if currency:
                untaxed, tax, total = (currency.round(v) for v in (untaxed, tax, total))
            order.x_cva_amount_untaxed = untaxed
            order.x_cva_amount_tax = tax
            order.x_cva_amount_total = total
            order.x_cva_amount_diff = (order.amount_total or 0.0) - total

    def _compute_x_cva_history_count(self):
        for order in self:
            order.x_cva_history_count = len(order.sudo().x_cva_history_ids)

    def _cva_ratio(self):
        """Proporción administrativo/registrado de la orden (1.0 sin ajuste)."""
        self.ensure_one()
        if self.amount_total:
            return (self.x_cva_amount_total or 0.0) / self.amount_total
        return 1.0 - (self.x_cva_percent or 0.0) / 100.0

    def _cva_paid_pairs(self):
        """[(factura, pagado_con_signo, proporción_administrativa)] de las
        facturas de cliente posteadas de la orden. Mismo criterio de 'pagado
        real' que usa todo el sistema (total − residual, refunds restan)."""
        self.ensure_one()
        pairs = []
        for inv in self.sudo().invoice_ids.filtered(
                lambda m: m.state == 'posted'
                and m.move_type in ('out_invoice', 'out_refund')):
            paid = (inv.amount_total or 0.0) - (inv.amount_residual or 0.0)
            if inv.move_type == 'out_refund':
                paid = -paid
            ratio = (inv.x_cva_amount_total / inv.amount_total) if inv.amount_total else 1.0
            pairs.append((inv, paid, ratio))
        return pairs

    def _compute_x_cva_payment_info(self):
        for order in self:
            pairs = order._cva_paid_pairs()
            paid = sum(p for _inv, p, _r in pairs)
            paid_adm = sum(p * r for _inv, p, r in pairs)
            order.x_cva_paid_amount = paid
            order.x_cva_paid_amount_adm = paid_adm
            order.x_cva_balance_adm = (order.x_cva_amount_total or 0.0) - paid_adm
            order.x_cva_payments_html = order._cva_payments_html(pairs)

    def _cva_payments_html(self, pairs):
        self.ensure_one()
        currency = self.currency_id
        symbol = currency.symbol or ''

        def money(value):
            return '%s %s%s' % (symbol, '{:,.{p}f}'.format(value or 0.0, p=currency.decimal_places or 2), '')

        payments = self.env['account.payment'].sudo()
        for inv, _p, _r in pairs:
            try:
                payments |= inv.sudo()._get_reconciled_payments()
            except Exception:  # noqa: BLE001
                _logger.exception('[CVA] no se pudieron listar pagos de %s', inv.name)
        if not payments:
            return Markup('<p class="text-muted mb-0">Sin pagos conciliados.</p>')
        rows = Markup('')
        for pay in payments.sorted(key=lambda p: (p.date or fields.Date.today(), p.id)):
            rows += Markup(
                '<tr><td>%s</td><td>%s</td><td class="text-end">%s</td>'
                '<td class="text-end">%s</td></tr>') % (
                escape(pay.name or ''),
                escape(str(pay.date or '')),
                escape(money(pay.amount)),
                escape(money(pay.x_cva_amount)),
            )
        return Markup(
            '<table class="table table-sm mb-0"><thead><tr>'
            '<th>Pago</th><th>Fecha</th>'
            '<th class="text-end">Registrado</th>'
            '<th class="text-end">Administrativo</th>'
            '</tr></thead><tbody>%s</tbody></table>') % rows

    # ------------------------------------------------------------------
    # Lente administrativa
    # ------------------------------------------------------------------
    def _cva_tax_totals(self):
        """Resumen de impuestos (widget tax_totals) sobre precios ajustados,
        con el mismo motor que el nativo."""
        self.ensure_one()
        AccountTax = self.env['account.tax']
        if hasattr(self, '_get_priced_lines'):
            lines = self._get_priced_lines()
        else:
            lines = self.order_line.filtered(lambda l: not l.display_type)
        base_lines = []
        for line in lines:
            factor = 1.0 - (line.x_cva_percent or 0.0) / 100.0
            base_lines.append(line._prepare_base_line_for_taxes_computation(
                price_unit=(line.price_unit or 0.0) * factor))
        if hasattr(self, '_add_base_lines_for_early_payment_discount'):
            base_lines += self._add_base_lines_for_early_payment_discount()
        AccountTax._add_tax_details_in_base_lines(base_lines, self.company_id)
        AccountTax._round_base_lines_tax_details(base_lines, self.company_id)
        return AccountTax._get_tax_totals_summary(
            base_lines=base_lines,
            currency=self.currency_id or self.company_id.currency_id,
            company=self.company_id,
        )

    def _cva_registered_payments_lensed(self):
        """Versión con lente de som_get_registered_payments (bloque de pagos
        de los reportes impresos)."""
        self.ensure_one()
        res = self.som_get_registered_payments()
        pairs = self._cva_paid_pairs()
        paid_adm = sum(p * r for _inv, p, r in pairs)
        total_adm = self.x_cva_amount_total or 0.0
        balance = paid_adm - total_adm
        rounding = self.currency_id.rounding or 0.01
        from odoo.tools import float_is_zero
        if float_is_zero(balance, precision_rounding=rounding):
            status, credit, due = 'paid', 0.0, 0.0
        elif balance > 0:
            status, credit, due = 'credit', balance, 0.0
        else:
            status, credit, due = 'due', 0.0, -balance
        res.update({'paid': paid_adm, 'balance': balance, 'status': status,
                    'credit': credit, 'due': due})
        return res

    def _cva_lens_map(self):
        def _scaled(name):
            return lambda o: (o[name] or 0.0) * o._cva_ratio()

        m = {
            'amount_untaxed': 'x_cva_amount_untaxed',
            'amount_tax': 'x_cva_amount_tax',
            'amount_total': 'x_cva_amount_total',
            'tax_totals': lambda o: o._cva_tax_totals(),
        }
        for opt in ('amount_to_invoice', 'amount_invoiced', 'amount_paid',
                    'amount_undiscounted',
                    # campos SOM opcionales (según módulos instalados)
                    'delivery_paid_amount', 'delivery_auth_authorized_amount',
                    'cash_received_amount', 'payment_proof_total',
                    'amount_pending_to_pay', 'kpi_amount_pending'):
            if opt in self._fields:
                m[opt] = _scaled(opt)
        if hasattr(type(self), 'som_get_registered_payments'):
            m['som_get_registered_payments'] = CvaMethod(
                lambda o: o._cva_registered_payments_lensed())
        return m

    # ------------------------------------------------------------------
    # Acciones (botones)
    # ------------------------------------------------------------------
    def _cva_check_manager(self):
        if not self.env.su and not self.env.user._has_group(CVA_MANAGER):
            raise AccessError(_(
                'Sólo el grupo Control de Valor Administrativo / '
                'Administrador puede aplicar o restablecer ajustes.'))

    def action_cva_open_apply_wizard(self):
        self.ensure_one()
        self._cva_check_manager()
        return {
            'name': _('Aplicar ajuste administrativo'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.cva.apply.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id},
        }

    def action_cva_open_reset_wizard(self):
        self.ensure_one()
        self._cva_check_manager()
        return {
            'name': _('Restablecer valor administrativo'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.cva.reset.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id},
        }

    def action_cva_view_history(self):
        self.ensure_one()
        return {
            'name': _('Historial administrativo'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.cva.history',
            'view_mode': 'list,form',
            'domain': [('order_id', '=', self.id)],
            'context': {'create': False},
        }

    # ------------------------------------------------------------------
    # Núcleo de negocio: aplicar / restablecer
    # ------------------------------------------------------------------
    def _cva_snapshot(self):
        self.ensure_one()
        lines = self.order_line.filtered(lambda l: not l.display_type)
        return {
            'percent': self.x_cva_percent or 0.0,
            'amount': self.x_cva_amount_total or 0.0,
            'lines': {
                l.id: {
                    'pct': l.x_cva_percent or 0.0,
                    'unit': l.x_cva_price_unit or 0.0,
                    'sub': l.x_cva_price_subtotal or 0.0,
                    'tot': l.x_cva_price_total or 0.0,
                } for l in lines
            },
        }

    def _cva_apply(self, percent, scope='order', line_ids=None, reason='',
                   keep_line_overrides=False):
        self.ensure_one()
        self._cva_check_manager()
        if self.state == 'cancel':
            raise UserError(_('No se aplica ajuste administrativo sobre una '
                              'orden cancelada.'))
        if not reason or not reason.strip():
            raise UserError(_('Captura el motivo del ajuste.'))
        if percent < 0 or percent > 100:
            raise UserError(_('El porcentaje debe estar entre 0%% y 100%%.'))
        before = self._cva_snapshot()
        now = fields.Datetime.now()
        user = self.env.user
        lines = self.order_line.filtered(lambda l: not l.display_type)
        header_vals = {
            'x_cva_active': True,
            'x_cva_state': 'applied',
            'x_cva_user_id': user.id,
            'x_cva_date': now,
            'x_cva_reason': reason.strip(),
        }
        if scope == 'order':
            header_vals['x_cva_percent'] = percent
            self.write(header_vals)
            if not keep_line_overrides:
                overridden = lines.filtered('x_cva_has_override')
                if overridden:
                    overridden.write({'x_cva_has_override': False,
                                      'x_cva_percent_override': 0.0})
            lines.write({'x_cva_write_uid': user.id, 'x_cva_write_date': now})
            action, affected = 'apply_order', lines
        else:
            affected = self.env['sale.order.line'].browse(line_ids or []) & lines
            if not affected:
                raise UserError(_('Selecciona al menos una línea.'))
            self.write(header_vals)
            affected.write({
                'x_cva_has_override': True,
                'x_cva_percent_override': percent,
                'x_cva_write_uid': user.id,
                'x_cva_write_date': now,
            })
            action = 'apply_lines'
        after = self._cva_snapshot()
        self._cva_log_history(action, reason, before, after, affected)
        self._cva_post_chatter(action, percent, reason, before, after)
        return True

    def _cva_reset(self, reason):
        self.ensure_one()
        self._cva_check_manager()
        if not reason or not reason.strip():
            raise UserError(_('Captura el motivo del restablecimiento.'))
        before = self._cva_snapshot()
        now = fields.Datetime.now()
        user = self.env.user
        lines = self.order_line.filtered(lambda l: not l.display_type)
        self.write({
            'x_cva_percent': 0.0,
            'x_cva_active': False,
            'x_cva_state': 'reset',
            'x_cva_user_id': user.id,
            'x_cva_date': now,
            'x_cva_reason': reason.strip(),
        })
        overridden = lines.filtered('x_cva_has_override')
        if overridden:
            overridden.write({'x_cva_has_override': False,
                              'x_cva_percent_override': 0.0})
        lines.write({'x_cva_write_uid': user.id, 'x_cva_write_date': now})
        after = self._cva_snapshot()
        self._cva_log_history('reset', reason, before, after, lines)
        self._cva_post_chatter('reset', 0.0, reason, before, after)
        return True

    def _cva_log_history(self, action, reason, before, after, lines):
        self.ensure_one()
        line_vals = []
        for line in lines:
            b = before['lines'].get(line.id, {})
            line_vals.append((0, 0, {
                'line_id': line.id,
                'product_id': line.product_id.id,
                'name': line.name or line.display_name,
                'qty': line.product_uom_qty,
                'percent_before': b.get('pct', 0.0),
                'percent_after': line.x_cva_percent,
                'price_unit_ref': line.x_cva_price_unit_ref,
                'price_unit_before': b.get('unit', 0.0),
                'price_unit_after': line.x_cva_price_unit,
                'subtotal_before': b.get('sub', 0.0),
                'subtotal_after': line.x_cva_price_subtotal,
                'total_before': b.get('tot', 0.0),
                'total_after': line.x_cva_price_total,
            }))
        self.env['sale.cva.history'].sudo().with_context(
            cva_history_maintenance=True).create({
                'order_id': self.id,
                'action': action,
                'user_id': self.env.user.id,
                'date': fields.Datetime.now(),
                'reason': reason.strip(),
                'percent_before': before['percent'],
                'percent_after': self.x_cva_percent or 0.0,
                'amount_before': before['amount'],
                'amount_after': after['amount'],
                'amount_reference': self.amount_total or 0.0,
                'line_ids': line_vals,
            })

    def _cva_post_chatter(self, action, percent, reason, before, after):
        self.ensure_one()
        labels = {
            'apply_order': _('Ajuste administrativo GENERAL aplicado'),
            'apply_lines': _('Ajuste administrativo POR LÍNEA aplicado'),
            'reset': _('Valor administrativo RESTABLECIDO'),
        }
        symbol = self.currency_id.symbol or ''

        def money(value):
            return '%s%s' % (symbol, '{:,.2f}'.format(value or 0.0))

        body = Markup(
            '<p><b>%s</b></p>'
            '<ul>'
            '<li>Porcentaje: %s%% → %s%%</li>'
            '<li>Total registrado: %s</li>'
            '<li>Total administrativo: %s → %s</li>'
            '<li>Motivo: %s</li>'
            '</ul>') % (
            escape(labels.get(action, action)),
            escape('{:.2f}'.format(before['percent'])),
            escape('{:.2f}'.format(self.x_cva_percent or 0.0)),
            escape(money(self.amount_total)),
            escape(money(before['amount'])),
            escape(money(after['amount'])),
            escape(reason.strip()),
        )
        try:
            self.sudo().message_post(
                body=body,
                subtype_xmlid='sale_admin_value_control.mt_cva',
                message_type='comment',
                author_id=self.env.user.partner_id.id,
            )
        except Exception:  # noqa: BLE001 - el chatter nunca bloquea el ajuste
            _logger.exception('[CVA] no se pudo publicar en el chatter de %s', self.name)
