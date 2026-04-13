import logging

from odoo import api, fields, models, SUPERUSER_ID
from odoo.http import request

_logger = logging.getLogger(__name__)


class ConsignmentPortalService(models.AbstractModel):
    _name = 'consignment.portal.service'
    _description = 'Consignment Portal Service'

    @api.model
    def _get_request_user(self):
        return request.env.user if request else self.env.user

    @api.model
    def get_current_portal_contact(self):
        user = self._get_request_user()
        partner = user.partner_id
        allowed = bool(user.has_group('base.group_portal') and partner.x_is_consigner)
        _logger.info(
            'Consignment access resolution: user_id=%s contact_partner_id=%s commercial_partner_id=%s allowed=%s',
            user.id,
            partner.id,
            partner.commercial_partner_id.id,
            allowed,
        )
        return partner if allowed else self.env['res.partner']

    @api.model
    def get_current_consigner_entity(self):
        contact = self.get_current_portal_contact()
        if not contact:
            return self.env['res.partner']
        company_partner = contact.commercial_partner_id
        valid = bool(company_partner.x_is_consigner)
        if not valid:
            _logger.warning(
                'Consignment company is not enabled: contact_partner_id=%s commercial_partner_id=%s',
                contact.id,
                company_partner.id,
            )
            return self.env['res.partner']
        return company_partner

    @api.model
    def portal_contact_can_access_consignment(self):
        return bool(self.get_current_portal_contact())

    @api.model
    def commercial_consigner_entity_is_valid(self):
        return bool(self.get_current_consigner_entity())

    @api.model
    def get_rfq_owner_partner(self):
        return self.get_current_portal_contact()

    @api.model
    def get_inventory_owner_partner(self):
        return self.get_current_consigner_entity()

    @api.model
    def can_view_rfq(self, rfq):
        owner = self.get_rfq_owner_partner()
        allowed = bool(
            rfq
            and rfq.exists()
            and rfq.x_portal_rfq
            and owner
            and rfq.partner_id.id == owner.id
        )
        if not allowed:
            _logger.warning('RFQ view denied: rfq_id=%s owner_partner_id=%s', rfq.id if rfq else None, owner.id if owner else None)
        return allowed

    @api.model
    def can_edit_rfq(self, rfq):
        allowed = bool(self.can_view_rfq(rfq) and rfq.state == 'draft' and not rfq.x_portal_submitted)
        if not allowed:
            _logger.warning('RFQ edit denied: rfq_id=%s', rfq.id if rfq else None)
        return allowed

    @api.model
    def get_allowed_rfq_products_domain(self, search=None):
        domain = [
            ('purchase_ok', '=', True),
            ('product_tmpl_id.x_rfq_portal_ok', '=', True),
            ('active', '=', True),
        ]
        if search:
            domain = ['|', ('name', 'ilike', search), ('default_code', 'ilike', search)] + domain
        return domain

    @api.model
    def get_active_rfq_cart(self):
        owner = self.get_rfq_owner_partner()
        if not owner:
            return self.env['purchase.order']
        cart = self.env['purchase.order'].search([
            ('partner_id', '=', owner.id),
            ('state', '=', 'draft'),
            ('x_portal_rfq', '=', True),
            ('x_portal_submitted', '=', False),
        ], limit=1)
        if cart:
            _logger.info('Active RFQ cart found: po_id=%s partner_id=%s', cart.id, owner.id)
        return cart

    @api.model
    def get_or_create_rfq_cart(self):
        cart = self.get_active_rfq_cart()
        if cart:
            return cart
        owner = self.get_rfq_owner_partner()
        if not owner:
            return self.env['purchase.order']
        company = self.env.company
        values = {
            'partner_id': owner.id,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'date_order': fields.Datetime.now(),
            'x_portal_rfq': True,
            'x_portal_submitted': False,
        }
        cart = self.env['purchase.order'].with_user(SUPERUSER_ID).create(values)
        _logger.info('RFQ cart created: po_id=%s partner_id=%s', cart.id, owner.id)
        return self.env['purchase.order'].browse(cart.id)
