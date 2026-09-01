# -*- coding: utf-8 -*-
"""Lente administrativa: sustitución de importes al PRESENTAR datos.

Un modelo que hereda ``sale.cva.lens.mixin`` declara en ``_cva_lens_map()``
qué campos nativos se presentan con su valor ajustado y de dónde sale ese
valor (otro campo almacenado, un callable o un método). La lente se aplica
únicamente en los puntos de entrada de presentación del cliente web:

* ``web_read`` / ``web_search_read`` / ``search_read`` (formularios, listas,
  kanban, widgets)
* ``formatted_read_group`` / ``web_read_group`` (totales de listas, pivote,
  gráficas)
* ``export_data`` (exportación ordinaria)
* reportes QWeb impresos desde el navegador (``/report/...``) vía CvaProxy

Nunca toca ``read()`` interno, ``write``, ``create`` ni la caché del ORM: la
lógica de negocio siempre trabaja con los valores reales.
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools import float_compare

from .cva_proxy import CvaMethod, lens_value

_logger = logging.getLogger(__name__)

CVA_MANAGER = 'sale_admin_value_control.group_cva_manager'
CVA_USER = 'sale_admin_value_control.group_cva_user'
CUSTOMER_MOVE_TYPES = ('out_invoice', 'out_refund', 'out_receipt')


class CvaLensMixin(models.AbstractModel):
    _name = 'sale.cva.lens.mixin'
    _description = 'Lente administrativa (mixin)'

    x_cva_lens_on = fields.Boolean(
        string='Vista administrativa activa',
        compute='_compute_x_cva_lens_on',
        help='Verdadero cuando el usuario actual ve el sistema con la lente '
             'administrativa. Se usa en las vistas para bloquear la captura '
             'de importes mientras la lente está encendida.')

    @api.depends_context('uid', 'cva_real')
    def _compute_x_cva_lens_on(self):
        on = self._cva_lens_active()
        for rec in self:
            rec.x_cva_lens_on = on

    # ------------------------------------------------------------------
    # Definición de la lente
    # ------------------------------------------------------------------
    def _cva_lens_map(self):
        """{campo_nativo: fuente}. Fuente: nombre de campo almacenado (str),
        callable(record) -> valor, o CvaMethod(fn) para métodos."""
        return {}

    @api.model
    def _cva_lens_active(self):
        return self.env['res.users']._cva_lens_active()

    def _cva_lens_names(self):
        return set(self._cva_lens_map().keys())

    # ------------------------------------------------------------------
    # Puntos de entrada de presentación
    # ------------------------------------------------------------------
    def _cva_apply_to_values(self, values_list, names):
        """Sustituye en ``values_list`` (una entrada por registro, ligada por
        id) los campos ``names`` por su valor con lente."""
        lens = self._cva_lens_map()
        wanted = [n for n in names if n in lens and not isinstance(lens[n], CvaMethod)]
        if not wanted:
            return
        by_id = {r.id: r for r in self}
        for vals in values_list:
            rec = by_id.get(vals.get('id'))
            if rec is None:
                continue
            for name in wanted:
                if name in vals:
                    try:
                        vals[name] = lens_value(rec, name)
                    except Exception:  # noqa: BLE001 - la lente nunca debe tumbar una lectura
                        _logger.exception('[CVA] lente: no se pudo ajustar %s en %s', name, rec)

    @api.readonly
    def web_read(self, specification):
        res = super().web_read(specification)
        if res and self._cva_lens_active():
            self._cva_apply_to_values(res, list(specification))
        return res

    @api.model
    @api.readonly
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None, **read_kwargs):
        res = super().search_read(domain=domain, fields=fields, offset=offset,
                                  limit=limit, order=order, **read_kwargs)
        if res and self._cva_lens_active():
            names = fields or list(self._cva_lens_names())
            records = self.browse([r['id'] for r in res if r.get('id')])
            records._cva_apply_to_values(res, names)
        return res

    @api.model
    @api.readonly
    def formatted_read_group(self, domain, groupby=(), aggregates=(), having=(), offset=0, limit=None, order=None):
        if not self._cva_lens_active():
            return super().formatted_read_group(domain, groupby, aggregates, having, offset, limit, order)
        lens = self._cva_lens_map()
        rewritten, python_aggs, rename = [], [], {}
        for spec in aggregates:
            fname, sep, agg = spec.partition(':')
            src = lens.get(fname) if sep else None
            if src is None:
                rewritten.append(spec)
            elif isinstance(src, str) and self._fields.get(src) is not None and self._fields[src].store:
                new_spec = f'{src}:{agg}'
                rewritten.append(new_spec)
                rename[new_spec] = spec
            elif isinstance(src, CvaMethod):
                rewritten.append(spec)
            else:
                rewritten.append(spec)
                python_aggs.append((spec, fname, agg))
        groups = super().formatted_read_group(domain, groupby, rewritten, having, offset, limit, order)
        if rename:
            for group in groups:
                for new_spec, old_spec in rename.items():
                    if new_spec in group:
                        group[old_spec] = group.pop(new_spec)
        if python_aggs and groups:
            base = Domain(domain if domain is not None else [])
            for group in groups:
                extra = group.get('__extra_domain')
                records = self.search(base & Domain(extra) if extra else base)
                for spec, fname, agg in python_aggs:
                    try:
                        values = [lens_value(r, fname) or 0.0 for r in records]
                        group[spec] = self._cva_python_aggregate(values, agg)
                    except Exception:  # noqa: BLE001
                        _logger.exception('[CVA] lente: agregado %s falló', spec)
        return groups

    @staticmethod
    def _cva_python_aggregate(values, agg):
        if not values:
            return 0.0 if agg in ('sum', 'avg') else False
        if agg == 'sum':
            return sum(values)
        if agg == 'avg':
            return sum(values) / len(values)
        if agg == 'max':
            return max(values)
        if agg == 'min':
            return min(values)
        if agg in ('count', 'count_distinct'):
            return len(values)
        return sum(values)

    @api.model
    def _cva_rewrite_export_path(self, path):
        """order_line/price_unit -> order_line/x_cva_price_unit_gross cuando la
        fuente es un campo almacenado; las fuentes callable no tienen columna,
        el campo se exporta tal cual (real)."""
        parts = path.split('/')
        model = self
        out = []
        for part in parts:
            name = part
            if model is not None and hasattr(model, '_cva_lens_map'):
                src = model._cva_lens_map().get(part)
                if isinstance(src, str) and model._fields.get(src) is not None:
                    name = src
            out.append(name)
            field = model._fields.get(part) if model is not None else None
            model = self.env[field.comodel_name] if field is not None and field.relational else None
        return '/'.join(out)

    def export_data(self, fields_to_export):
        if self._cva_lens_active():
            fields_to_export = [self._cva_rewrite_export_path(f) for f in fields_to_export]
        return super().export_data(fields_to_export)

    # ------------------------------------------------------------------
    # Candado de captura bajo lente
    # ------------------------------------------------------------------
    def _cva_guard_vals(self, vals):
        """Con la lente encendida el formulario muestra importes ajustados;
        guardar uno de esos importes escribiría el valor ajustado sobre el
        real. Se bloquea, salvo que el valor coincida con el real actual."""
        lens = self._cva_lens_map()
        blocked = []
        for name, value in vals.items():
            src = lens.get(name)
            field = self._fields.get(name)
            if src is None or isinstance(src, CvaMethod) or field is None:
                continue
            if field.type not in ('float', 'monetary', 'integer'):
                continue
            if len(self) == 1 and self.id:
                real = self[name] or 0.0
                try:
                    if float_compare(float(value or 0.0), float(real), precision_digits=6) == 0:
                        continue
                except (TypeError, ValueError):
                    pass
            blocked.append(field.string or name)
        if blocked:
            raise UserError(_(
                'Estás viendo el sistema con la VISTA ADMINISTRATIVA encendida, '
                'así que los importes en pantalla llevan el ajuste aplicado. '
                'Para modificar importes reales apaga la vista administrativa '
                '(indicador en la barra superior) y vuelve a intentarlo.\n\n'
                'Campos bloqueados: %s') % ', '.join(blocked))
        # comandos x2many hacia comodelos con lente (líneas del formulario)
        for name, value in vals.items():
            field = self._fields.get(name)
            if field is None or field.type not in ('one2many', 'many2many') or not isinstance(value, list):
                continue
            comodel = self.env[field.comodel_name]
            if not hasattr(comodel, '_cva_guard_vals'):
                continue
            for cmd in value:
                if isinstance(cmd, (list, tuple)) and len(cmd) == 3 and cmd[0] == 1 and isinstance(cmd[2], dict):
                    comodel.browse(cmd[1])._cva_guard_vals(cmd[2])

    def web_save(self, vals, specification, next_id=None):
        if vals and self._cva_lens_active():
            self._cva_guard_vals(vals)
        return super().web_save(vals, specification, next_id=next_id)

    def web_save_multi(self, vals_list, specification):
        if self._cva_lens_active():
            for record, vals in zip(self, vals_list):
                record._cva_guard_vals(vals)
        return super().web_save_multi(vals_list, specification)
