# -*- coding: utf-8 -*-
"""Control administrativo sobre las Entradas de Caja.

* Estatus administrativo (Pendiente / Parcial / Depositado): qué tan
  depositado está el efectivo. Es un semáforo que el administrador cambia
  con un clic desde la lista (widget cva_deposit_state), independiente del
  estado operativo de la entrada.
* El estado operativo solo tiene dos valores (Registrada / Cancelada): una
  entrada cancelada se ARCHIVA (active = False) y desaparece de las listas;
  no hace falta mostrarlo como columna.
"""
from odoo import api, fields, models


class CashEntry(models.Model):
    _inherit = 'cash.entry'

    active = fields.Boolean(string='Activo', default=True)

    x_cva_deposit_state = fields.Selection([
        ('pending', 'Pendiente'),
        ('partial', 'Parcial'),
        ('deposited', 'Depositado'),
    ], string='Estatus administrativo', default='pending', required=True,
        tracking=True, index=True,
        help='Control administrativo del efectivo de esta entrada: pendiente de '
             'depositar, depositado parcialmente o depositado por completo. '
             'Se cambia con un clic sobre la etiqueta en la lista.')

    x_cva_order_ids = fields.Many2many(
        'sale.order', string='Pedidos', compute='_compute_x_cva_order_ids',
        help='Pedidos ligados a la entrada; si no tiene, los del recibo que la respalda.')

    @api.depends('sale_order_ids', 'receipt_id.sale_order_ids')
    def _compute_x_cva_order_ids(self):
        for rec in self:
            orders = rec.sale_order_ids
            if not orders and rec.receipt_id:
                orders = rec.receipt_id.sale_order_ids
            rec.x_cva_order_ids = orders

    # ------------------------------------------------------------------
    # Cancelada = archivada
    # ------------------------------------------------------------------
    def action_cancel(self):
        res = super().action_cancel()
        self.write({'active': False})
        return res

    def action_restore(self):
        res = super().action_restore()
        self.write({'active': True})
        return res

    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals and 'active' not in vals:
            # Cualquier ruta que cancele/restaure mantiene el archivado en línea.
            for rec in self:
                wanted = rec.state != 'cancelled'
                if rec.active != wanted:
                    super(CashEntry, rec).write({'active': wanted})
        return res

    @api.model
    def _cva_archive_cancelled(self):
        """Idempotente (corre en cada -u): las entradas canceladas quedan
        archivadas y las registradas visibles."""
        entries = self.with_context(active_test=False).sudo().search([])
        to_archive = entries.filtered(lambda e: e.state == 'cancelled' and e.active)
        to_restore = entries.filtered(lambda e: e.state != 'cancelled' and not e.active)
        if to_archive:
            to_archive.write({'active': False})
        if to_restore:
            to_restore.write({'active': True})
        return True
