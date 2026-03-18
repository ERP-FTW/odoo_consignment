from datetime import datetime, time, timedelta

from odoo import fields, http
from odoo.http import request
from werkzeug.exceptions import NotFound


class ConsignmentPortalStock(http.Controller):

    def _get_consigner_partner_or_404(self):
        commercial_partner = request.env.user.partner_id.commercial_partner_id
        if not commercial_partner.x_is_consigner:
            raise NotFound()
        return commercial_partner

    def _parse_date(self, raw_value):
        if not raw_value:
            return None
        try:
            return datetime.strptime(raw_value, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            return None

    @http.route('/my/consign/stock', type='http', auth='user', website=True)
    def portal_consign_stock(self, q=None, date_from=None, date_to=None, **kwargs):
        consigner_partner = self._get_consigner_partner_or_404()

        today = fields.Date.context_today(request.env.user)
        default_date_to = today
        default_date_from = today - timedelta(days=29)

        parsed_date_from = self._parse_date(date_from) or default_date_from
        parsed_date_to = self._parse_date(date_to) or default_date_to
        if parsed_date_from > parsed_date_to:
            parsed_date_from = default_date_from
            parsed_date_to = default_date_to

        product_ids = None
        clean_q = (q or '').strip()
        if clean_q:
            products = request.env['product.product'].sudo().search([
                '|',
                ('name', 'ilike', clean_q),
                ('default_code', 'ilike', clean_q),
            ])
            product_ids = products.ids

        product_filter_domain = [('product_id', 'in', product_ids)] if product_ids is not None else []

        Quant = request.env['stock.quant'].sudo()
        on_hand_domain = [
            ('owner_id', '=', consigner_partner.id),
            ('quantity', '>', 0),
            ('location_id.usage', '=', 'internal'),
            *product_filter_domain,
        ]
        on_hand_grouped = Quant.read_group(
            on_hand_domain,
            fields=['product_id', 'quantity:sum'],
            groupby=['product_id'],
            lazy=False,
        )

        date_from_dt = datetime.combine(parsed_date_from, time.min)
        date_to_dt = datetime.combine(parsed_date_to, time.max)
        MoveLine = request.env['stock.move.line'].sudo()
        sold_domain = [
            ('owner_id', '=', consigner_partner.id),
            ('state', '=', 'done'),
            ('move_id.location_dest_id.usage', '=', 'customer'),
            ('date', '>=', fields.Datetime.to_string(date_from_dt)),
            ('date', '<=', fields.Datetime.to_string(date_to_dt)),
            *product_filter_domain,
        ]
        sold_grouped = MoveLine.read_group(
            sold_domain,
            fields=['product_id', 'quantity:sum'],
            groupby=['product_id'],
            lazy=False,
        )

        product_map = {}
        product_ids_in_rows = {
            row['product_id'][0]
            for row in (on_hand_grouped + sold_grouped)
            if row.get('product_id')
        }
        if product_ids_in_rows:
            products = request.env['product.product'].sudo().browse(product_ids_in_rows)
            product_map = {product.id: product for product in products}

        on_hand_rows = []
        for row in on_hand_grouped:
            if not row.get('product_id'):
                continue
            product_id = row['product_id'][0]
            on_hand_rows.append({
                'product': product_map.get(product_id),
                'qty_on_hand': row.get('quantity', 0.0),
            })
        on_hand_rows.sort(key=lambda row: row['qty_on_hand'], reverse=True)

        sold_rows = []
        for row in sold_grouped:
            if not row.get('product_id'):
                continue
            product_id = row['product_id'][0]
            sold_rows.append({
                'product': product_map.get(product_id),
                'qty_sold': row.get('quantity', 0.0),
            })
        sold_rows.sort(key=lambda row: row['qty_sold'], reverse=True)

        values = {
            'q': clean_q,
            'date_from': parsed_date_from.strftime('%Y-%m-%d'),
            'date_to': parsed_date_to.strftime('%Y-%m-%d'),
            'on_hand_rows': on_hand_rows,
            'on_hand_total_qty': sum(row['qty_on_hand'] for row in on_hand_rows),
            'on_hand_product_count': len(on_hand_rows),
            'sold_rows': sold_rows,
            'sold_total_qty': sum(row['qty_sold'] for row in sold_rows),
            'sold_product_count': len(sold_rows),
        }
        return request.render('consignment_portal_stock_mvp.portal_consign_stock_page', values)