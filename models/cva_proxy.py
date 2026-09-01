# -*- coding: utf-8 -*-
"""Proxy de presentación para la lente administrativa en reportes QWeb.

Los reportes (OV, detalle, recibo, factura) reciben en ``docs`` un CvaProxy
en lugar del recordset real. El proxy responde a los mismos atributos que el
registro; para los campos del mapa de lente (``_cva_lens_map``) devuelve el
valor ajustado y para todo lo demás delega al registro real. Los recordsets
relacionados de modelos con lente (líneas, pagos, órdenes de un recibo) se
envuelven a su vez, así una plantilla escrita contra el registro real imprime
valores ajustados sin modificar el QWeb.

Compatible con ``t-field`` (usa ``record._fields[name]`` y ``record[name]``)
y con ``web.external_layout`` (``'company_id' in o``, ``o.company_id.sudo()``).
"""
from odoo import models


class CvaMethod:
    """Marca una entrada del mapa de lente que representa un MÉTODO del
    registro: el proxy devuelve un callable que invoca ``fn(record, *a, **k)``
    y envuelve el resultado."""
    __slots__ = ('fn',)

    def __init__(self, fn):
        self.fn = fn


def _has_lens(value):
    return isinstance(value, models.BaseModel) and hasattr(value, '_cva_lens_map')


def cva_wrap(value):
    """Envuelve recordsets de modelos con lente; el resto pasa intacto."""
    if _has_lens(value):
        return CvaProxy(value)
    if isinstance(value, dict):
        return {k: cva_wrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [cva_wrap(v) for v in value]
    if isinstance(value, tuple):
        return tuple(cva_wrap(v) for v in value)
    return value


def cva_unwrap(value):
    if isinstance(value, CvaProxy):
        return object.__getattribute__(value, '_cva_rec')
    return value


def lens_value(record, name):
    """Valor con lente del campo ``name`` sobre un registro singleton."""
    src = record._cva_lens_map().get(name)
    if src is None:
        return record[name]
    if isinstance(src, str):
        return record[src]
    if isinstance(src, CvaMethod):
        return src.fn(record)
    return src(record)


class CvaProxy:
    __slots__ = ('_cva_rec',)

    def __init__(self, rec):
        object.__setattr__(self, '_cva_rec', rec)

    # ---- acceso a atributos -------------------------------------------
    def __getattr__(self, name):
        rec = object.__getattribute__(self, '_cva_rec')
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        if len(rec) == 1:
            src = rec._cva_lens_map().get(name)
            if src is not None:
                if isinstance(src, CvaMethod):
                    fn = src.fn
                    return lambda *a, **k: cva_wrap(fn(rec, *a, **k))
                if isinstance(src, str):
                    return cva_wrap(rec[src])
                return cva_wrap(src(rec))
        if name in ('filtered', 'sorted', 'mapped', 'grouped', 'filtered_domain'):
            return getattr(self, '_cva_' + name)
        value = getattr(rec, name)
        if callable(value) and not isinstance(value, models.BaseModel):
            def _call(*args, **kwargs):
                args = tuple(cva_unwrap(a) for a in args)
                kwargs = {k: cva_unwrap(v) for k, v in kwargs.items()}
                return cva_wrap(value(*args, **kwargs))
            return _call
        return cva_wrap(value)

    def __setattr__(self, name, value):
        raise AttributeError('CvaProxy es de sólo lectura (%s)' % name)

    def __getitem__(self, key):
        rec = object.__getattribute__(self, '_cva_rec')
        if isinstance(key, str):
            return getattr(self, key)
        return cva_wrap(rec[key])

    def __contains__(self, item):
        rec = object.__getattribute__(self, '_cva_rec')
        return cva_unwrap(item) in rec

    def __iter__(self):
        rec = object.__getattribute__(self, '_cva_rec')
        for r in rec:
            yield CvaProxy(r)

    def __len__(self):
        return len(object.__getattribute__(self, '_cva_rec'))

    def __bool__(self):
        return bool(object.__getattribute__(self, '_cva_rec'))

    def __eq__(self, other):
        return object.__getattribute__(self, '_cva_rec') == cva_unwrap(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(object.__getattribute__(self, '_cva_rec'))

    def __repr__(self):
        return 'CvaProxy(%r)' % (object.__getattribute__(self, '_cva_rec'),)

    def __str__(self):
        return str(object.__getattribute__(self, '_cva_rec'))

    # ---- operadores de recordset --------------------------------------
    def __or__(self, other):
        return cva_wrap(object.__getattribute__(self, '_cva_rec') | cva_unwrap(other))

    def __add__(self, other):
        return cva_wrap(object.__getattribute__(self, '_cva_rec') + cva_unwrap(other))

    def __sub__(self, other):
        return cva_wrap(object.__getattribute__(self, '_cva_rec') - cva_unwrap(other))

    def __and__(self, other):
        return cva_wrap(object.__getattribute__(self, '_cva_rec') & cva_unwrap(other))

    def __lt__(self, other):
        return object.__getattribute__(self, '_cva_rec') < cva_unwrap(other)

    # ---- helpers funcionales que reciben lambdas ----------------------
    def _cva_filtered(self, func):
        rec = object.__getattribute__(self, '_cva_rec')
        if isinstance(func, str):
            return cva_wrap(rec.filtered(lambda r: getattr(CvaProxy(r), func)))
        return cva_wrap(rec.filtered(lambda r: func(CvaProxy(r))))

    def _cva_filtered_domain(self, domain):
        rec = object.__getattribute__(self, '_cva_rec')
        return cva_wrap(rec.filtered_domain(domain))

    def _cva_sorted(self, key=None, reverse=False):
        rec = object.__getattribute__(self, '_cva_rec')
        if key is None or isinstance(key, str):
            return cva_wrap(rec.sorted(key=key, reverse=reverse))
        return cva_wrap(rec.sorted(key=lambda r: key(CvaProxy(r)), reverse=reverse))

    def _cva_mapped(self, func):
        rec = object.__getattribute__(self, '_cva_rec')
        if isinstance(func, str):
            if '.' in func:
                current = [CvaProxy(r) for r in rec]
                for part in func.split('.'):
                    nxt = []
                    for item in current:
                        value = getattr(item, part)
                        if isinstance(value, CvaProxy):
                            nxt.extend(list(value))
                        elif isinstance(value, models.BaseModel):
                            nxt.extend(list(value))
                        else:
                            nxt.append(value)
                    current = nxt
                return current
            if not rec:
                return cva_wrap(rec.mapped(func))
            field = rec._fields.get(func)
            if field is not None and field.relational:
                return cva_wrap(rec.mapped(func))
            return [getattr(CvaProxy(r), func) for r in rec]
        return [func(CvaProxy(r)) for r in rec]

    def _cva_grouped(self, key):
        rec = object.__getattribute__(self, '_cva_rec')
        groups = {}
        for r in rec:
            k = getattr(CvaProxy(r), key) if isinstance(key, str) else key(CvaProxy(r))
            groups.setdefault(k, rec.browse())
            groups[k] |= r
        return {k: cva_wrap(v) for k, v in groups.items()}
