# Control de Valor Administrativo (CVA)

Módulo Odoo 19 Enterprise · SOM Group · `sale_admin_value_control`

Porcentaje de **ajuste administrativo interno** sobre órdenes de venta
(equivalente a una comisión entre socios). Produce un juego completo de
**valores paralelos** (`x_cva_*`) y una **lente de presentación** para que el
único usuario autorizado vea *todo el sistema* con el ajuste aplicado,
mientras vendedores, contabilidad y clientes siguen viendo los valores
reales. **La contabilidad y lo fiscal quedan intactos siempre.**

## Ejemplo

| Concepto | Valor |
|---|---|
| Precio registrado | $100.00 |
| % de ajuste | 40% |
| Valor administrativo | $60.00 |
| Pago registrado | $100.00 |
| Pago administrativo (lente) | $60.00 |
| Diferencia administrativa | $40.00 (sólo indicador) |

Fórmula: `precio_adm = precio_referencia × (1 − %/100)` donde
`precio_referencia = price_unit × (1 − descuento_comercial/100)`.
Los impuestos administrativos se calculan con los MISMOS impuestos de la
línea y el mismo motor fiscal de Odoo; el redondeo respeta la moneda.
El % particular de una línea prevalece sobre el general de la orden.

## Grupos

* **Control de Valor Administrativo / Consulta** — ve el % y los valores
  administrativos (pestaña de la orden, columnas opcionales, historial,
  reportes). No aplica, no modifica, no restablece. Sin lente.
* **Control de Valor Administrativo / Administrador** — aplica/restablece
  porcentajes, configura porcentajes rápidos y tiene la **lente
  administrativa**. Pensado para UN usuario específico.
* El administrador general de Odoo **no** obtiene acceso automáticamente:
  hay que agregarlo expresamente a un grupo. El superusuario técnico
  (`__system__`) conserva su paso para mantenimiento, salvo el historial.

## La lente administrativa

Interruptor en la barra superior (píldora **VISTA OPERATIVA / VISTA
ADMINISTRATIVA**), sólo visible para el Administrador. Encendida (estado por defecto):

* Órdenes, líneas, facturas de cliente, pagos y recibos de efectivo se
  presentan con el ajuste aplicado — formularios, listas, totales de grupo,
  kanban, pivotes/gráficas (`sale.report`, `account.invoice.report`),
  exportaciones.
* Los **mismos botones de impresión** entregan el PDF ajustado: Orden de
  Venta, Orden de Venta - Detalle, Recibo de Efectivo, y el botón
  *Imprimir (administrativa)* de la factura.
* Los importes en pantalla quedan **bloqueados contra guardado**: si se
  intenta guardar un importe bajo lente, el sistema pide apagarla (evita
  escribir el valor ajustado sobre el real). La lógica de negocio interna
  siempre usa los valores reales.

La lente **no** aplica jamás en: correos y plantillas (adjuntos), portal del
cliente, WhatsApp, EDI/CFDI, crons ni llamadas con `sudo()`. El PDF legal de
la factura (Enviar e imprimir) siempre es real. Técnica: la sustitución de
impresos sólo ocurre en peticiones interactivas `/report/...` (o el contexto
de pruebas `cva_lens_print`); las lecturas sólo en `web_read`,
`web_search_read`, `search_read`, `formatted_read_group` y `export_data`.
Cualquier flujo puede forzar valores reales con `context['cva_real']=True`.

> Tableros a medida con SQL crudo (`/som/analytics`, KPIs) se integran por
> fases con el helper de mapeo de columnas; hasta entonces muestran valores
> reales (ver "Fase 2" abajo).

## Operación

1. **Aplicar**: botón *Aplicar ajuste administrativo* en la orden →
   porcentaje (o botón rápido 10/20/30/40/50, configurables en
   *Configuración → Porcentajes rápidos*), alcance (toda la orden / líneas
   seleccionadas), motivo opcional y vista previa por línea.
   Aplicar el general limpia los % particulares salvo que se marque
   *Conservar porcentajes particulares*.
2. **Restablecer**: botón *Restablecer valor administrativo* → confirma,
   motivo opcional, deja el % en 0 y conserva el historial.
3. **Consultar**: pestaña *Control administrativo* de la orden (comparativa
   registrado vs administrativo, pagos, detalle por línea), menú raíz
   *Control de Valor Administrativo* (ventas con control, análisis, historial).
4. **Trazabilidad**: cada aplicación/restablecimiento crea una entrada
   inmutable en el historial (antes/después por orden y por línea), visible
   sólo para los grupos CVA. **No se publica nada en el chatter** de la
   orden: el ajuste no deja rastro en la interfaz para nadie. Los mensajes
   que versiones anteriores publicaron se purgan en cada actualización.

## Aislamiento (garantías)

* Jamás se escribe en `price_unit`, `discount`, `price_subtotal`,
  `price_total`, `amount_untaxed`, `amount_tax`, `amount_total` ni en
  facturas, pagos, conciliaciones o asientos.
* Duplicar una orden (o sus COT/ de respaldo) nace sin control (`copy=False`).
* Los campos `x_cva_*` llevan `groups=` a nivel ORM: usuarios sin grupo
  reciben `AccessError` en lectura, escritura, exportación y búsqueda
  (Odoo 19 valida dominios), y no los ven en `fields_get`.
* El historial no se puede modificar ni borrar (ni siquiera superusuario,
  salvo contexto técnico `cva_history_maintenance` para recuperación).
* Integraciones: un usuario técnico de integración NO debe pertenecer a los
  grupos CVA salvo que la integración esté autorizada a ver estos valores.

## Pruebas

`tests/` cubre cálculo (motor fiscal, descuentos, particulares, límites,
redondeo), permisos (vendedor, admin general, consulta, administrador,
chatter, multiempresa), lente (web_read, agrupados, exportación, candado de
guardado, impresos, pagos, recibo), aislamiento (factura + pago intactos,
duplicado limpio, documentos del cliente reales) e historial (entradas,
inmutabilidad, restablecimiento). Ejecutar en QA:

```bash
docker compose run --rm --no-deps odoo19-qa odoo -c /etc/odoo/odoo.conf \
  -d somgroup --stop-after-init --test-enable \
  --test-tags /sale_admin_value_control -u sale_admin_value_control
```

## Fase 2 (pendiente acordada)

Extender la lente a los tableros SOM con SQL crudo: `/som/analytics`
(stock_transit_allocation), KPIs de la orden, estado de cuenta, comisiones y
caja. Patrón: sustituir columnas `price_subtotal`/`amount_total` por
`x_cva_*` en las consultas cuando `env['res.users']._cva_lens_active()`.
