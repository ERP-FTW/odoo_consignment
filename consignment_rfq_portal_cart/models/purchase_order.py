from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    x_portal_rfq = fields.Boolean(string='Portal RFQ', default=False)
    x_portal_submitted = fields.Boolean(string='Portal Submitted', default=False)
    x_portal_submitted_date = fields.Datetime(string='Portal Submitted Date')
    x_portal_notes = fields.Text(string='Portal Notes')
