import logging
from datetime import datetime, time, timedelta

from odoo import fields, http
from odoo.http import request
from werkzeug.exceptions import NotFound

_logger = logging.getLogger(__name__)


class ConsignmentPortalDashboard(http.Controller):

    def _consignment_service(self):
        return request.env['consignment.portal.service']

    def _ensure_access(self):
        service = self._consignment_service()
        contact = service.get_current_portal_contact()
        company = service.get_current_consigner_entity()
        if not contact or not company:
            _logger.warning('Consignment dashboard access denied: user_id=%s', request.env.user.id)
            raise NotFound()
        return contact, company

    def _parse_date(self, raw_value):
        if not raw_value:
            return None
        try:
            return datetime.strptime(raw_value, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            return None

    def _product_search_ids(self, q):
        clean_q = (q or '').strip()
        if not clean_q:
            return clean_q, None
        products = request.env['product.product'].sudo().search([
            '|', ('name', 'ilike', clean_q), ('default_code', 'ilike', clean_q),
        ])
        return clean_q, products.ids

    def _build_stock_sales_rows(self, owner, q=None, date_from=None, date_to=None):
        today = fields.Date.context_today(request.env.user)
        default_date_to = today
        default_date_from = today - timedelta(days=29)

        parsed_date_from = self._parse_date(date_from) or default_date_from
        parsed_date_to = self._parse_date(date_to) or default_date_to
        if parsed_date_from > parsed_date_to:
            parsed_date_from = default_date_from
            parsed_date_to = default_date_to

        clean_q, product_ids = self._product_search_ids(q)
        product_filter_domain = [('product_id', 'in', product_ids)] if product_ids is not None else []

        on_hand_grouped = request.env['stock.quant'].sudo().read_group(
            [
                ('owner_id', '=', owner.id),
                ('quantity', '>', 0),
                ('location_id.usage', '=', 'internal'),
                *product_filter_domain,
            ],
            fields=['product_id', 'quantity:sum'],
            groupby=['product_id'],
            lazy=False,
        )

        sold_grouped = request.env['stock.move.line'].sudo().read_group(
            [
                ('owner_id', '=', owner.id),
                ('state', '=', 'done'),
                ('move_id.location_dest_id.usage', '=', 'customer'),
                ('date', '>=', fields.Datetime.to_string(datetime.combine(parsed_date_from, time.min))),
                ('date', '<=', fields.Datetime.to_string(datetime.combine(parsed_date_to, time.max))),
                *product_filter_domain,
            ],
            fields=['product_id', 'quantity:sum'],
            groupby=['product_id'],
            lazy=False,
        )

        product_ids_in_rows = {row['product_id'][0] for row in (on_hand_grouped + sold_grouped) if row.get('product_id')}
        product_map = {}
        if product_ids_in_rows:
            products = request.env['product.product'].sudo().browse(product_ids_in_rows)
            product_map = {product.id: product for product in products}

        on_hand_rows = []
        for row in on_hand_grouped:
            if not row.get('product_id'):
                _logger.warning('On-hand row without product_id for owner_id=%s', owner.id)
                continue
            product_id = row['product_id'][0]
            on_hand_rows.append({'product': product_map.get(product_id), 'qty_on_hand': row.get('quantity', 0.0)})

        sold_rows = []
        for row in sold_grouped:
            if not row.get('product_id'):
                _logger.warning('Sold row without product_id for owner_id=%s', owner.id)
                continue
            product_id = row['product_id'][0]
            sold_rows.append({'product': product_map.get(product_id), 'qty_sold': row.get('quantity', 0.0)})

        on_hand_rows.sort(key=lambda row: row['qty_on_hand'], reverse=True)
        sold_rows.sort(key=lambda row: row['qty_sold'], reverse=True)

        _logger.info(
            'Dashboard aggregation: owner_id=%s on_hand_products=%s sold_products=%s q=%s',
            owner.id,
            len(on_hand_rows),
            len(sold_rows),
            clean_q,
        )
        return {
            'q': clean_q,
            'date_from': parsed_date_from.strftime('%Y-%m-%d'),
            'date_to': parsed_date_to.strftime('%Y-%m-%d'),
            'on_hand_rows': on_hand_rows,
            'sold_rows': sold_rows,
            'on_hand_total_qty': sum(row['qty_on_hand'] for row in on_hand_rows),
            'on_hand_product_count': len(on_hand_rows),
            'sold_total_qty': sum(row['qty_sold'] for row in sold_rows),
            'sold_product_count': len(sold_rows),
        }

    def _build_rfq_summary(self, contact):
        PurchaseOrder = request.env['purchase.order']
        base_domain = [('partner_id', '=', contact.id), ('x_portal_rfq', '=', True)]
        draft_cart = PurchaseOrder.search(base_domain + [('state', '=', 'draft'), ('x_portal_submitted', '=', False)], limit=1)

        pending_states = ['draft', 'sent', 'to approve']
        pending_rfqs = PurchaseOrder.search(
            base_domain + [('x_portal_submitted', '=', True), ('state', 'in', pending_states)],
            limit=5,
            order='x_portal_submitted_date desc, id desc',
        )
        accepted_rfqs = PurchaseOrder.search(
            base_domain + [('x_portal_submitted', '=', True), ('state', 'in', ['purchase', 'done'])],
            limit=5,
            order='x_portal_submitted_date desc, id desc',
        )
        return {
            'draft_cart': draft_cart,
            'pending_rfqs': pending_rfqs,
            'accepted_rfqs': accepted_rfqs,
            'pending_count': PurchaseOrder.search_count(base_domain + [('x_portal_submitted', '=', True), ('state', 'in', pending_states)]),
            'accepted_count': PurchaseOrder.search_count(base_domain + [('x_portal_submitted', '=', True), ('state', 'in', ['purchase', 'done'])]),
        }

    @http.route(['/my/consign', '/my/consign/stock'], type='http', auth='user', website=True)
    def portal_consign_dashboard(self, q=None, date_from=None, date_to=None, **kwargs):
        contact, company = self._ensure_access()
        values = {
            **self._build_stock_sales_rows(company, q=q, date_from=date_from, date_to=date_to),
            **self._build_rfq_summary(contact),
        }
        return request.render('consignment_portal_dashboard.portal_consign_dashboard', values)
