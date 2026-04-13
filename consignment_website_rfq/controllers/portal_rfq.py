import logging

from odoo import _, fields, http
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.tools import float_is_zero
from odoo.addons.portal.controllers.portal import pager as portal_pager
from werkzeug.exceptions import NotFound
from werkzeug.utils import redirect

_logger = logging.getLogger(__name__)


class ConsignmentWebsiteRfqPortal(http.Controller):

    def _consignment_service(self):
        return request.env['consignment.portal.service']

    def _ensure_consigner_contact(self):
        partner = self._consignment_service().get_current_portal_contact()
        if not partner:
            _logger.warning('RFQ portal access denied: user_id=%s', request.env.user.id)
            raise NotFound()
        return partner

    def _active_cart(self):
        return self._consignment_service().get_active_rfq_cart()

    @http.route('/my/consign/rfq', type='http', auth='user', website=True)
    def consign_rfq_products(self, search=None, page=1, **kwargs):
        self._ensure_consigner_contact()
        Product = request.env['product.product']
        domain = self._consignment_service().get_allowed_rfq_products_domain(search=search)
        total = Product.search_count(domain)
        page = int(page)
        pager = portal_pager(
            url='/my/consign/rfq',
            url_args={'search': search} if search else {},
            total=total,
            page=page,
            step=20,
        )
        products = Product.search(domain, limit=20, offset=pager['offset'])
        cart = self._active_cart()
        values = {
            'products': products,
            'search': search,
            'cart': cart,
            'cart_line_count': len(cart.order_line),
            'pager': pager,
            'error': kwargs.get('error'),
        }
        return request.render('consignment_website_rfq.portal_rfq_products', values)

    @http.route('/my/consign/rfq/add', type='http', auth='user', website=True, methods=['POST'])
    def consign_rfq_add(self, product_id=None, qty=None, **kwargs):
        partner = self._ensure_consigner_contact()
        try:
            quantity = float(qty or 0.0)
        except (TypeError, ValueError):
            quantity = 0.0
        if quantity <= 0:
            _logger.warning('Invalid RFQ add quantity: partner_id=%s qty=%s', partner.id, qty)
            return redirect('/my/consign/rfq?error=qty')

        product = request.env['product.product'].browse(int(product_id or 0))
        if not product.exists() or not product.purchase_ok or not product.product_tmpl_id.x_rfq_portal_ok:
            _logger.warning('Invalid RFQ add product: partner_id=%s product_id=%s', partner.id, product_id)
            return redirect('/my/consign/rfq?error=product')

        cart = self._consignment_service().get_or_create_rfq_cart()
        line = cart.order_line.filtered(
            lambda l: l.product_id == product and float_is_zero(l.price_unit, precision_rounding=0.00001)
        )[:1]
        if line:
            line.product_qty += quantity
            _logger.info('RFQ cart line quantity incremented: po_id=%s line_id=%s qty=%s', cart.id, line.id, quantity)
        else:
            request.env['purchase.order.line'].create({
                'order_id': cart.id,
                'product_id': product.id,
                'product_qty': quantity,
                'product_uom': product.uom_po_id.id,
                'price_unit': 0.0,
                'name': product.display_name,
                'date_planned': fields.Datetime.now(),
            })
            _logger.info('RFQ cart line created: po_id=%s product_id=%s qty=%s', cart.id, product.id, quantity)
        return redirect('/my/consign/rfq')

    @http.route('/my/consign/rfq/cart', type='http', auth='user', website=True)
    def consign_rfq_cart(self, **kwargs):
        self._ensure_consigner_contact()
        cart = self._active_cart()
        return request.render('consignment_website_rfq.portal_rfq_cart', {'cart': cart, 'error': kwargs.get('error')})

    @http.route('/my/consign/rfq/cart/update', type='http', auth='user', website=True, methods=['POST'])
    def consign_rfq_cart_update(self, x_portal_notes=None, **post):
        partner = self._ensure_consigner_contact()
        cart = self._active_cart()
        if not cart:
            _logger.warning('RFQ cart update with no active cart: partner_id=%s', partner.id)
            return redirect('/my/consign/rfq/cart')
        if not self._consignment_service().can_edit_rfq(cart):
            raise AccessError(_('Submitted RFQs cannot be modified.'))

        for line in cart.order_line:
            key = f'qty_{line.id}'
            if key not in post:
                continue
            try:
                quantity = float(post.get(key) or 0.0)
            except (TypeError, ValueError):
                quantity = 0.0
            if quantity <= 0:
                _logger.info('RFQ cart line removed: po_id=%s line_id=%s partner_id=%s', cart.id, line.id, partner.id)
                line.unlink()
            else:
                _logger.info('RFQ cart line updated: po_id=%s line_id=%s qty=%s partner_id=%s', cart.id, line.id, quantity, partner.id)
                line.product_qty = quantity

        cart.x_portal_notes = x_portal_notes
        _logger.info('RFQ cart notes updated: po_id=%s partner_id=%s', cart.id, partner.id)
        return redirect('/my/consign/rfq/cart')

    @http.route('/my/consign/rfq/submit', type='http', auth='user', website=True, methods=['POST'])
    def consign_rfq_submit(self, **kwargs):
        partner = self._ensure_consigner_contact()
        cart = self._active_cart()
        if not cart:
            _logger.warning('RFQ submit attempted without cart: partner_id=%s', partner.id)
            return redirect('/my/consign/rfq/cart')
        if not cart.order_line:
            _logger.warning('RFQ submit attempted with empty cart: po_id=%s partner_id=%s', cart.id, partner.id)
            return redirect('/my/consign/rfq/cart?error=empty')

        cart.write({'x_portal_submitted': True, 'x_portal_submitted_date': fields.Datetime.now()})

        body = _('Portal RFQ submitted by %s.') % partner.display_name
        if cart.x_portal_notes:
            body = '%s<br/>%s' % (body, _('Notes: %s') % cart.x_portal_notes)
        cart.message_post(body=body)

        managers = request.env.ref('purchase.group_purchase_manager').users
        for manager in managers:
            cart.sudo().activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=manager.id,
                note=_('Review submitted portal RFQ from partner %s.') % partner.display_name,
            )
        _logger.info('RFQ submitted: po_id=%s partner_id=%s manager_count=%s', cart.id, partner.id, len(managers))
        return redirect('/my/consign/rfq/%s' % cart.id)

    @http.route('/my/consign/rfqs', type='http', auth='user', website=True)
    def consign_rfq_list(self, page=1, **kwargs):
        partner = self._ensure_consigner_contact()
        page = int(page)
        domain = [('partner_id', '=', partner.id), ('x_portal_rfq', '=', True), ('x_portal_submitted', '=', True)]
        PurchaseOrder = request.env['purchase.order']
        total = PurchaseOrder.search_count(domain)
        pager = portal_pager(url='/my/consign/rfqs', total=total, page=page, step=20)
        orders = PurchaseOrder.search(domain, limit=20, offset=pager['offset'], order='x_portal_submitted_date desc, id desc')
        return request.render('consignment_website_rfq.portal_rfq_list', {'rfqs': orders, 'pager': pager})

    @http.route('/my/consign/rfq/<int:po_id>', type='http', auth='user', website=True)
    def consign_rfq_detail(self, po_id, **kwargs):
        self._ensure_consigner_contact()
        rfq = request.env['purchase.order'].browse(po_id)
        if not self._consignment_service().can_view_rfq(rfq):
            raise NotFound()
        return request.render('consignment_website_rfq.portal_rfq_detail', {'rfq': rfq})
