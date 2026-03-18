from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_is_consigner = fields.Boolean(
        string='Consigner',
        help='Grants access to the Consign RFQ portal pages.',
    )
