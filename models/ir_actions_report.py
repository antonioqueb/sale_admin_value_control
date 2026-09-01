# -*- coding: utf-8 -*-
"""Impresos con lente: el MISMO botón de impresión (OV, detalle, recibo de
efectivo, factura administrativa) entrega valores ajustados al usuario con la
lente encendida.

La lente en impresos sólo aplica a peticiones interactivas del navegador
(``/report/pdf``, ``/report/html``, ``/report/download``) o con el contexto
explícito ``cva_lens_print``. Cualquier PDF generado por correo, WhatsApp,
portal, EDI o crons sale con valores reales aunque lo dispare el usuario con
la lente: esos flujos no pasan por ``/report/``.
"""
from odoo import models
from odoo.http import request

from .cva_proxy import CvaProxy


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _cva_print_lens_active(self):
        if not self.env['res.users']._cva_lens_active():
            return False
        if self.env.context.get('cva_lens_print'):
            return True
        try:
            path = request.httprequest.path if request else ''
        except Exception:  # noqa: BLE001
            path = ''
        return bool(path) and path.startswith('/report/')

    def _get_rendering_context(self, report, docids, data):
        data = super()._get_rendering_context(report, docids, data)
        if self._cva_print_lens_active():
            docs = data.get('docs')
            if isinstance(docs, models.BaseModel) and hasattr(docs, '_cva_lens_map'):
                data['docs'] = CvaProxy(docs)
                data['cva_lens'] = True
        return data
