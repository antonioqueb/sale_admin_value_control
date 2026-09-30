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
        ('order', 'Toda la orden con el mismo %'),
        ('lines', 'Un % distinto por producto'),
    ], string='¿Cómo quieres aplicarlo?', required=True, default='order')
    percent = fields.Float(string='Porcentaje de ajuste', digits=(5, 2), required=True)
    quick_id = fields.Many2one(
        'sale.cva.quick.percent', string='Opciones rápidas',
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    keep_line_overrides = fields.Boolean(
        string='Respetar los productos que ya tienen su propio %',
        help='Al aplicar el porcentaje general, las líneas que ya tienen un '
             'porcentaje particular lo conservan. Si se deja apagado, los '
             'particulares se limpian y toda la orden queda con el general.')
    reason = fields.Char(string='Motivo')
    line_ids = fields.One2many(
        'sale.cva.apply.wizard.line', 'wizard_id', string='Líneas')

    total_ref = fields.Monetary(
        string='Total de la orden', compute='_compute_preview')
    total_adm_current = fields.Monetary(
        string='Total administrativo hoy', compute='_compute_preview')
    total_adm_new = fields.Monetary(
        string='Total administrativo con este ajuste', compute='_compute_preview')
    diff_new = fields.Monetary(
        string='Se descuenta', compute='_compute_preview')
    subtotal_adm_new = fields.Monetary(
        string='Subtotal con ajuste (sin IVA)', compute='_compute_preview')
    below_cost = fields.Boolean(compute='_compute_preview')
    total_cost_all_in = fields.Monetary(
        string='Costo all-in (sin IVA)', compute='_compute_preview',
        help='Suma del costo ALL-IN (base + logística + arancel) de las '
             'líneas, en la divisa de la orden y sin IVA. Sirve de piso '
             'para decidir cuánto ajustar.')
    # Totales de las columnas nuevas. Utilidad sobre las líneas CON costo
    # all-in (las que no lo tienen saldrían con 100 % y la inflarían).
    total_margin_current = fields.Float(
        string='Utilidad hoy', compute='_compute_preview', digits=(16, 4))
    total_margin_new = fields.Float(
        string='Nueva utilidad', compute='_compute_preview', digits=(16, 4))
    total_invoiced = fields.Monetary(
        string='Facturado', compute='_compute_preview',
        help='Suma de lo capturado en Facturado. Solo referencia: no entra '
             'en ningún cálculo.')
    invoiced_lines_label = fields.Char(compute='_compute_preview')

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
            res.setdefault('percent', order.x_cva_percent or 0.0)
            scope = res.get('scope') or 'order'
            # Un solo botón guarda Facturado y aplica: si la orden ya trae %
            # por línea, se abre respetándolos para que guardar sin tocar
            # porcentajes no los limpie.
            lines = order.order_line.filtered(lambda l: not l.display_type)
            if 'default_keep_line_overrides' not in self.env.context \
                    and any(lines.mapped('x_cva_has_override')):
                res['keep_line_overrides'] = True
            keep = res.get('keep_line_overrides')
            lines_vals = []
            for line in lines:
                pct = self._cva_preview_percent(
                    line, True, res['percent'], scope, keep)
                lines_vals.append((0, 0, dict(
                    line_id=line.id, selected=True,
                    invoiced_amount=line.x_cva_invoiced_amount or 0.0,
                    **self._cva_preview_vals(line, pct))))
            res['line_ids'] = lines_vals
        return res

    @api.model
    def _cva_preview_percent(self, line, selected, percent, scope, keep):
        """% que quedaría en la línea al confirmar con la captura actual."""
        if scope == 'order':
            if keep and line.x_cva_has_override:
                return line.x_cva_percent_override or 0.0
            return percent
        if selected:
            return percent
        return line.x_cva_percent or 0.0

    @api.model
    def _cva_preview_vals(self, line, pct):
        return {
            'percent_new': pct,
            'subtotal_adm_new': (line.price_subtotal or 0.0) * (1.0 - pct / 100.0),
        }

    # VISTA PREVIA EN VIVO: la escribe el onchange del wizard sobre cada
    # línea. Como compute de la línea dependiente del padre (wizard_id.*)
    # el formulario no la refrescaba al elegir el porcentaje rápido ni al
    # prender/apagar líneas.
    # "Por línea": el % general (rápido o escrito) llena las líneas
    # seleccionadas; después cada línea se edita sola (su propio rápido o
    # escrito a mano) y NO se pisa al tocar otras líneas: por eso aquí no
    # se escucha line_ids.
    @api.onchange('percent', 'scope', 'keep_line_overrides')
    def _onchange_cva_preview(self):
        for wiz in self:
            for wline in wiz.line_ids:
                if wline.line_id:
                    wline.quick_id = False
                    wline.update(wiz._cva_preview_vals(
                        wline.line_id, wiz._cva_preview_percent(
                            wline.line_id, wline.selected, wiz.percent,
                            wiz.scope, wiz.keep_line_overrides)))

    @api.onchange('quick_id')
    def _onchange_quick_id(self):
        if self.quick_id:
            self.percent = self.quick_id.percent
        self._onchange_cva_preview()

    def _line_new_percent(self, wline):
        self.ensure_one()
        if self.scope == 'lines':
            if wline.selected:
                return wline.percent_new or 0.0
            return wline.line_id.x_cva_percent or 0.0
        return self._cva_preview_percent(
            wline.line_id, wline.selected, self.percent, self.scope,
            self.keep_line_overrides)

    @api.depends('percent', 'scope', 'keep_line_overrides',
                 'line_ids.selected', 'line_ids.percent_new',
                 'line_ids.cost_all_in', 'line_ids.invoiced_amount',
                 'line_ids.subtotal_adm_current', 'order_id')
    def _compute_preview(self):
        for wiz in self:
            order = wiz.order_id
            total_ref = order.amount_total or 0.0
            total_new = sub_new = 0.0
            cost_sum = cur_with_cost = new_with_cost = 0.0
            for wline in wiz.line_ids:
                line = wline.line_id
                pct_new = wiz._line_new_percent(wline)
                line_sub_new = (line.price_subtotal or 0.0) * (1.0 - pct_new / 100.0)
                total_new += (line.price_total or 0.0) * (1.0 - pct_new / 100.0)
                sub_new += line_sub_new
                if wline.cost_all_in:
                    cost_sum += wline.cost_all_in
                    cur_with_cost += wline.subtotal_adm_current or 0.0
                    new_with_cost += line_sub_new
            wiz.total_margin_current = (cur_with_cost - cost_sum) / cur_with_cost \
                if cost_sum and cur_with_cost else 0.0
            wiz.total_margin_new = (new_with_cost - cost_sum) / new_with_cost \
                if cost_sum and new_with_cost else 0.0
            invoiced = wiz.line_ids.filtered(lambda w: (w.invoiced_amount or 0.0) > 0)
            wiz.total_invoiced = sum(invoiced.mapped('invoiced_amount'))
            wiz.invoiced_lines_label = _('%(n)s de %(t)s líneas') % {
                'n': len(invoiced), 't': len(wiz.line_ids)}
            if order.currency_id:
                total_new = order.currency_id.round(total_new)
            wiz.total_ref = total_ref
            wiz.total_adm_current = order.x_cva_amount_total or 0.0
            wiz.total_adm_new = total_new
            wiz.diff_new = total_ref - total_new
            wiz.total_cost_all_in = sum(wiz.line_ids.mapped('cost_all_in'))
            wiz.subtotal_adm_new = sub_new
            # Aviso: con este ajuste la orden queda por debajo de su costo.
            wiz.below_cost = bool(wiz.total_cost_all_in) and \
                sub_new < wiz.total_cost_all_in - 0.005

    def _cva_percent_changes(self):
        """¿La captura cambia algún porcentaje? Si solo se tocó Facturado,
        no se re-aplica el ajuste (ni se escribe historial)."""
        self.ensure_one()
        order = self.order_id
        differs = lambda a, b: abs((a or 0.0) - (b or 0.0)) > 0.005  # noqa: E731
        wlines = self.line_ids.filtered('line_id')
        if self.scope == 'lines':
            return any(
                differs(w.percent_new, w.line_id.x_cva_percent)
                for w in wlines if w.selected)
        if differs(self.percent, order.x_cva_percent):
            return True
        if not self.keep_line_overrides and any(
                wlines.mapped('line_id.x_cva_has_override')):
            return True
        return any(
            differs(self._line_new_percent(w), w.line_id.x_cva_percent)
            for w in wlines)

    def action_confirm(self):
        """Botón único: aplica el ajuste si cambió algún porcentaje y
        guarda el Facturado capturado."""
        self.ensure_one()
        order = self.order_id
        order._cva_check_manager()
        if self.scope == 'lines':
            selected = self.line_ids.filtered(lambda w: w.selected and w.line_id)
            if not selected:
                raise UserError(_('Selecciona al menos una línea.'))
        if self._cva_percent_changes():
            if self.scope == 'lines':
                order._cva_apply(
                    self.percent, scope='lines', reason=self.reason,
                    line_percents={w.line_id.id: w.percent_new or 0.0
                                   for w in selected})
            else:
                order._cva_apply(self.percent, scope='order', reason=self.reason,
                                 keep_line_overrides=self.keep_line_overrides)
        self._cva_save_invoiced()
        return {'type': 'ir.actions.act_window_close'}

    def _cva_save_invoiced(self):
        """Guarda el Facturado capturado por línea (solo lo que cambió)."""
        self.ensure_one()
        for wline in self.line_ids.filtered('line_id'):
            line = wline.line_id
            amount = wline.invoiced_amount or 0.0
            if self.currency_id.compare_amounts(
                    amount, line.x_cva_invoiced_amount or 0.0) != 0:
                line.write({'x_cva_invoiced_amount': amount})


class SaleCvaApplyWizardLine(models.TransientModel):
    _name = 'sale.cva.apply.wizard.line'
    _description = 'Aplicar ajuste administrativo (línea)'

    wizard_id = fields.Many2one(
        'sale.cva.apply.wizard', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='wizard_id.currency_id')
    company_id = fields.Many2one(related='wizard_id.company_id')
    selected = fields.Boolean(string='Ajustar', default=True)
    line_id = fields.Many2one(
        'sale.order.line', string='Línea', required=True, ondelete='cascade')
    product_id = fields.Many2one(related='line_id.product_id')
    name = fields.Text(related='line_id.name', string='Descripción')
    qty = fields.Float(related='line_id.product_uom_qty', string='Cantidad')
    uom_id = fields.Many2one(related='line_id.product_uom_id', string='Unidad')
    price_unit_ref = fields.Float(
        related='line_id.x_cva_price_unit_ref', string='Precio unitario')
    percent_current = fields.Float(
        related='line_id.x_cva_percent', string='Ajuste hoy (%)')
    has_override = fields.Boolean(
        related='line_id.x_cva_has_override', string='Tiene su propio %')
    subtotal_adm_current = fields.Monetary(
        related='line_id.x_cva_price_subtotal', string='Importe hoy')
    # Los llena el onchange del wizard (_onchange_cva_preview): vista
    # previa en vivo. En "Por línea" percent_new es editable (rápido de la
    # línea o escrito a mano) y ES el % que se aplica a esa línea.
    quick_id = fields.Many2one(
        'sale.cva.quick.percent', string='Opción rápida',
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    percent_new = fields.Float(string='Ajuste a aplicar (%)', digits=(5, 2))
    subtotal_adm_new = fields.Monetary(string='Importe con ajuste')
    # Utilidad sobre costo ALL-IN, misma fórmula que el Margen All-In % de
    # la orden: (subtotal − costo) / subtotal. Razón (0.35 = 35 %).
    margin_current = fields.Float(
        string='Utilidad hoy', compute='_compute_margins', digits=(16, 4),
        help='Utilidad sobre el costo all-in con el importe administrativo '
             'actual: (importe − costo) / importe. Vacía si el producto no '
             'tiene costo all-in.')
    margin_new = fields.Float(
        string='Nueva utilidad', compute='_compute_margins', digits=(16, 4),
        help='Utilidad sobre el costo all-in con el ajuste capturado.')
    invoiced_amount = fields.Monetary(
        string='Facturado',
        help='Monto facturado de la línea. Si es mayor a cero la línea se '
             'marca en verde. Se guarda al aplicar.')
    cost_all_in = fields.Monetary(
        string='Costo all-in', compute='_compute_cost_all_in',
        help='Costo ALL-IN del producto (base + logística + arancel) × '
             'cantidad, en la divisa de la orden y sin IVA. Mismo costo '
             'que usa el Margen All-In % de la orden.')

    @api.constrains('percent_new')
    def _check_percent_new(self):
        for wline in self:
            if wline.percent_new < 0 or wline.percent_new > 100:
                raise ValidationError(_(
                    'El porcentaje debe estar entre 0%% y 100%% '
                    '(capturaste %.2f%%).') % wline.percent_new)

    def _cva_refresh_subtotal(self):
        for wline in self:
            if wline.line_id:
                wline.subtotal_adm_new = (wline.line_id.price_subtotal or 0.0) \
                    * (1.0 - (wline.percent_new or 0.0) / 100.0)

    @api.onchange('quick_id')
    def _onchange_line_quick_id(self):
        for wline in self:
            if wline.quick_id:
                wline.percent_new = wline.quick_id.percent
        self._cva_refresh_subtotal()

    @api.onchange('percent_new')
    def _onchange_line_percent_new(self):
        for wline in self:
            if wline.quick_id and wline.quick_id.percent != wline.percent_new:
                wline.quick_id = False
        self._cva_refresh_subtotal()

    @api.onchange('selected')
    def _onchange_line_selected(self):
        # Apagada = se queda como está; encendida = arranca con el general.
        for wline in self:
            wline.quick_id = False
            if wline.selected:
                wline.percent_new = wline.wizard_id.percent or 0.0
            else:
                wline.percent_new = wline.line_id.x_cva_percent or 0.0
        self._cva_refresh_subtotal()

    @api.depends('line_id', 'line_id.product_id', 'line_id.product_uom_qty')
    def _compute_cost_all_in(self):
        for wline in self:
            wline.cost_all_in = wline.line_id._cva_cost_all_in() \
                if wline.line_id else 0.0

    @api.depends('cost_all_in', 'subtotal_adm_current', 'subtotal_adm_new')
    def _compute_margins(self):
        for wline in self:
            cost = wline.cost_all_in or 0.0
            cur_sub = wline.subtotal_adm_current or 0.0
            new_sub = wline.subtotal_adm_new or 0.0
            wline.margin_current = (cur_sub - cost) / cur_sub if cost and cur_sub else 0.0
            wline.margin_new = (new_sub - cost) / new_sub if cost and new_sub else 0.0
