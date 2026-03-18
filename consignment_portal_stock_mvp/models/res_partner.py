from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_is_consigner = fields.Boolean(default=False)
