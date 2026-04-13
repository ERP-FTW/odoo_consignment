{
    'name': 'Consignment Website RFQ',
    'summary': 'Website-style RFQ builder for consignment portal users',
    'version': '18.0.1.0.0',
    'category': 'Website/Portal',
    'author': 'Odoo Community',
    'license': 'LGPL-3',
    'depends': ['consignment_portal_base', 'website', 'portal', 'purchase', 'mail'],
    'data': [
        'views/portal_rfq_templates.xml',
    ],
    'installable': True,
    'application': False,
}
