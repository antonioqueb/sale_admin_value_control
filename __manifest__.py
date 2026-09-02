# -*- coding: utf-8 -*-
{
    'name': 'Control de Valor Administrativo',
    'version': '19.0.1.3.0',
    'category': 'Sales/Sales',
    'icon': '/sale_admin_value_control/static/description/icon.svg',
    'summary': 'Porcentaje de ajuste administrativo sobre órdenes de venta con '
               'valores paralelos, lente de presentación y trazabilidad',
    'description': """
Control de Valor Administrativo (CVA)
=====================================
* Porcentaje de ajuste administrativo por orden o por línea, en campos
  propios (x_cva_*) que JAMÁS escriben sobre los campos nativos.
* Dos grupos: Consulta y Administrador. El administrador general de Odoo no
  obtiene acceso automáticamente.
* Lente administrativa: el usuario Administrador ve TODO con el ajuste
  aplicado (órdenes, facturas, pagos, análisis, impresos), el resto ve lo
  operativo. La lente sustituye valores sólo al presentar; contabilidad,
  facturas, pagos y conciliaciones quedan intactos.
* Historial inmutable (sólo grupos CVA), sin rastro en el chatter, reportes
  administrativos.
""",
    'author': 'Alphaqueb Consulting',
    'license': 'LGPL-3',
    'depends': [
        'sale_management',
        'account',
        'stock_lot_dimensions',
        'cash_receipt_voucher',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'security/multi_company_rules.xml',
        'data/cva_data.xml',
        'wizard/cva_apply_wizard_views.xml',
        'wizard/cva_reset_wizard_views.xml',
        'views/cva_history_views.xml',
        'views/cva_quick_percent_views.xml',
        'views/sale_order_views.xml',
        'views/account_views.xml',
        'views/cash_receipt_views.xml',
        'views/sale_report_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sale_admin_value_control/static/src/cva_lens/cva_lens.js',
            'sale_admin_value_control/static/src/cva_lens/cva_lens.scss',
        ],
    },
    'installable': True,
    'application': True,
}
