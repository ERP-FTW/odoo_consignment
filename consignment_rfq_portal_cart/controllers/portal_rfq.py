import logging

from odoo import _, fields, http, SUPERUSER_ID
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.tools import float_is_zero
from odoo.addons.portal.controllers.portal import pager as portal_pager
from werkzeug.exceptions import Forbidden, NotFound
from werkzeug.utils import redirect

_logger = logging.getLogger(__name__)


class ConsignmentRfqPortal(http.Controller):

    def _check_consigner_access(self):
        user = request.env.user
        partner = user.partner_id
        if not user.has_group('base.group_portal') or not partner.x_is_consigner:
            raise Forbidden()
        return partner

    def _get_active_cart(self, partner):
        return request.env['purchase.order'].search([
            ('partner_id', '=', partner.id),
            ('state', '=', 'draft'),
            ('x_portal_rfq', '=', True),
            ('x_portal_submitted', '=', False),
        ], limit=1)

    def _get_or_create_cart(self, partner):
        cart = self._get_active_cart(partner)
        if cart:
            return cart
        company = request.env.company
        values = {
            'partner_id': partner.id,
            'company_id': company.id,
            'currency_id': company.currency_id.id,
            'date_order': fields.Datetime.now(),
            'x_portal_rfq': True,
            'x_portal_submitted': False,
        }
        # Portal users cannot access ir.sequence. Creating the PO with superuser
        # avoids sequence access errors while keeping ownership on partner_id.
        cart = request.env['purchase.order'].with_user(SUPERUSER_ID).create(values)
        _logger.info('Portal RFQ cart created: po_id=%s partner_id=%s', cart.id, partner.id)
        return request.env['purchase.order'].browse(cart.id)

    def _get_allowed_products_domain(self, search=None):
        domain = [
            ('purchase_ok', '=', True),
            ('product_tmpl_id.x_rfq_portal_ok', '=', True),
            ('active', '=', True),
        ]
        if search:
            domain = ['|', ('name', 'ilike', search), ('default_code', 'ilike', search)] + domain
        return domain

    @http.route('/my/consign', type='http', auth='user', website=True)
    def consign_landing(self, **kwargs):
        self._check_consigner_access()
        return request.render('consignment_rfq_portal_cart.portal_consign_landing')

    @http.route('/my/consign/rfq', type='http', auth='user', website=True)
    def consign_rfq_products(self, search=None, page=1, **kwargs):
        partner = self._check_consigner_access()
        Product = request.env['product.product']
        domain = self._get_allowed_products_domain(search=search)
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
        cart = self._get_active_cart(partner)
        values = {
            'products': products,
            'search': search,
            'cart': cart,
            'cart_line_count': len(cart.order_line),
            'pager': pager,
            'error': kwargs.get('error'),
        }
        return request.render('consignment_rfq_portal_cart.portal_rfq_products', values)

    @http.route('/my/consign/rfq/add', type='http', auth='user', website=True, methods=['POST'])
    def consign_rfq_add(self, product_id=None, qty=None, **kwargs):
        partner = self._check_consigner_access()
        try:
            quantity = float(qty or 0.0)
        except (TypeError, ValueError):
            quantity = 0.0
        if quantity <= 0:
            _logger.warning('Portal RFQ invalid quantity: partner_id=%s qty=%s', partner.id, qty)
            return redirect('/my/consign/rfq?error=qty')
        product = request.env['product.product'].browse(int(product_id or 0))
        if not product.exists() or not product.purchase_ok or not product.product_tmpl_id.x_rfq_portal_ok:
            _logger.warning('Portal RFQ disallowed product: partner_id=%s product_id=%s', partner.id, product_id)
            return redirect('/my/consign/rfq?error=product')

        cart = self._get_or_create_cart(partner)
        line = cart.order_line.filtered(lambda l: l.product_id == product and float_is_zero(l.price_unit, precision_rounding=0.00001))[:1]
        if line:
            line.product_qty += quantity
            _logger.info('Portal RFQ line updated: po_id=%s partner_id=%s product_id=%s', cart.id, partner.id, product.id)
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
            _logger.info('Portal RFQ line created: po_id=%s partner_id=%s product_id=%s', cart.id, partner.id, product.id)
        return redirect('/my/consign/rfq')

    @http.route('/my/consign/rfq/cart', type='http', auth='user', website=True)
    def consign_rfq_cart(self, **kwargs):
        partner = self._check_consigner_access()
        cart = self._get_active_cart(partner)
        return request.render('consignment_rfq_portal_cart.portal_rfq_cart', {
            'cart': cart,
            'error': kwargs.get('error'),
        })

    @http.route('/my/consign/rfq/cart/update', type='http', auth='user', website=True, methods=['POST'])
    def consign_rfq_cart_update(self, x_portal_notes=None, **post):
        partner = self._check_consigner_access()
        cart = self._get_active_cart(partner)
        if not cart:
            _logger.warning('Portal RFQ update without cart: partner_id=%s', partner.id)
            return redirect('/my/consign/rfq/cart')
        if cart.x_portal_submitted:
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
                line.unlink()
            else:
                line.product_qty = quantity

        cart.x_portal_notes = x_portal_notes
        _logger.info('Portal RFQ cart updated: po_id=%s partner_id=%s', cart.id, partner.id)
        return redirect('/my/consign/rfq/cart')

    @http.route('/my/consign/rfq/submit', type='http', auth='user', website=True, methods=['POST'])
    def consign_rfq_submit(self, **kwargs):
        partner = self._check_consigner_access()
        cart = self._get_active_cart(partner)
        if not cart:
            _logger.warning('Portal RFQ submit without cart: partner_id=%s', partner.id)
            return redirect('/my/consign/rfq/cart')
        if not cart.order_line:
            _logger.warning('Portal RFQ submit empty cart: po_id=%s partner_id=%s', cart.id, partner.id)
            return redirect('/my/consign/rfq/cart?error=empty')

        cart.write({
            'x_portal_submitted': True,
            'x_portal_submitted_date': fields.Datetime.now(),
        })

        msg = _('Portal RFQ submitted by %s.') % partner.display_name
        if cart.x_portal_notes:
            msg = '%s<br/>%s' % (msg, _('Notes: %s') % cart.x_portal_notes)
        cart.message_post(body=msg)

        managers = request.env.ref('purchase.group_purchase_manager').users
        for manager in managers:
            cart.sudo().activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=manager.id,
                note=_('Review submitted portal RFQ from partner %s.') % partner.display_name,
            )
        _logger.info('Portal RFQ submitted: po_id=%s partner_id=%s', cart.id, partner.id)
        return redirect('/my/consign/rfq/%s' % cart.id)

    @http.route('/my/consign/rfqs', type='http', auth='user', website=True)
    def consign_rfq_list(self, page=1, **kwargs):
        partner = self._check_consigner_access()
        page = int(page)
        domain = [
            ('partner_id', '=', partner.id),
            ('x_portal_rfq', '=', True),
            ('x_portal_submitted', '=', True),
        ]
        PurchaseOrder = request.env['purchase.order']
        total = PurchaseOrder.search_count(domain)
        pager = portal_pager(url='/my/consign/rfqs', total=total, page=page, step=20)
        orders = PurchaseOrder.search(domain, limit=20, offset=pager['offset'], order='x_portal_submitted_date desc, id desc')
        return request.render('consignment_rfq_portal_cart.portal_rfq_list', {
            'rfqs': orders,
            'pager': pager,
        })

    @http.route('/my/consign/rfq/<int:po_id>', type='http', auth='user', website=True)
    def consign_rfq_detail(self, po_id, **kwargs):
        partner = self._check_consigner_access()
        rfq = request.env['purchase.order'].browse(po_id)
        if not rfq.exists() or rfq.partner_id != partner or not rfq.x_portal_rfq:
            raise NotFound()
        return request.render('consignment_rfq_portal_cart.portal_rfq_detail', {'rfq': rfq})