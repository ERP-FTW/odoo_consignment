from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    x_rfq_portal_ok = fields.Boolean(
        string='RFQ Portal',
        help='Allow requesting this product via portal RFQ cart.',
    )
