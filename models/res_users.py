# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import AccessError

from .cva_lens import CVA_MANAGER


class ResUsers(models.Model):
    _inherit = 'res.users'

    x_cva_lens = fields.Boolean(
        string='Vista administrativa',
        default=True,
        help='Sólo tiene efecto para el grupo Control de Valor Administrativo '
             '/ Administrador: encendida, todo se presenta con el ajuste '
             'administrativo aplicado; apagada, vista operativa (valores '
             'registrados).')

    @api.model
    def _cva_lens_active(self):
        """La lente aplica cuando: el usuario ES el administrador CVA, la
        tiene encendida, no se está en sudo y nadie forzó ``cva_real``."""
        env = self.env
        if env.su or env.context.get('cva_real'):
            return False
        user = env.user
        if not user or not user.id:
            return False
        try:
            if not user._has_group(CVA_MANAGER):
                return False
        except Exception:  # noqa: BLE001 - módulo a medio instalar
            return False
        return bool(user.sudo().x_cva_lens)

    @api.model
    def _cva_lens_available(self):
        user = self.env.user
        if not user or not user.id:
            return False
        try:
            return bool(user._has_group(CVA_MANAGER))
        except Exception:  # noqa: BLE001
            return False

    @api.model
    def action_cva_toggle_lens(self):
        user = self.env.user
        if not user._has_group(CVA_MANAGER):
            raise AccessError('La vista administrativa es exclusiva del grupo '
                              'Control de Valor Administrativo / Administrador.')
        new_state = not user.sudo().x_cva_lens
        user.sudo().write({'x_cva_lens': new_state})
        return new_state

    @api.model
    def cva_lens_state(self):
        return {
            'available': self._cva_lens_available(),
            'on': self._cva_lens_active(),
        }
