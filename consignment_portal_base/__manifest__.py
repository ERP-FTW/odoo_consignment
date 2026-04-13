{
    'name': 'Consignment Portal Base',
    'summary': 'Shared consignment portal fields, access, and helpers',
    'version': '18.0.1.0.0',
    'category': 'Website/Portal',
    'author': 'Odoo Community',
    'license': 'LGPL-3',
    'depends': ['portal', 'website', 'purchase', 'stock', 'mail', 'product'],
    'data': [
        'security/ir.model.access.csv',
        'security/consignment_portal_security.xml',
        'views/partner_views.xml',
        'views/product_views.xml',
        'views/purchase_order_views.xml',
        'views/portal_menu.xml',
    ],
    'installable': True,
    'application': False,
}
