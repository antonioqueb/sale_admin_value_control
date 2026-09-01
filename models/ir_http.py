# -*- coding: utf-8 -*-
from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        info = super().session_info()
        try:
            info['cva_lens'] = self.env['res.users'].cva_lens_state()
        except Exception:  # noqa: BLE001 - jamás romper el arranque del cliente
            info['cva_lens'] = {'available': False, 'on': False}
        return info
