# Consignment RFQ Portal Cart

Portal consigners can create a draft purchase RFQ using a cart workflow and submit it for internal review.

## Features

- Product flag `RFQ Portal` (`product.template.x_rfq_portal_ok`) to control which products are available in the portal picker.
- Partner flag `Consigner` (`res.partner.x_is_consigner`) to grant access to portal consign pages.
- Portal routes:
  - `/my/consign`
  - `/my/consign/rfq`
  - `/my/consign/rfq/cart`
  - `/my/consign/rfqs`
  - `/my/consign/rfq/<po_id>`
- Cart stored as draft `purchase.order` with:
  - `x_portal_rfq`
  - `x_portal_submitted`
  - `x_portal_submitted_date`
  - `x_portal_notes`
- Submission posts chatter message and creates review activities for Purchase Managers.
- Purchase app filters for portal RFQ tracking.

## Security

Portal users can only access their own portal RFQs:

- Read own `purchase.order` where `x_portal_rfq = True`
- Write/create only while `x_portal_submitted = False`
- Read own `purchase.order.line`; write/create/unlink only before submission

## Acceptance Test Checklist

1. Create product A and set **RFQ Portal = True**.
2. Create product B and set **RFQ Portal = False**.
3. Create partner Vendor1, set **Consigner = True**, and grant portal access.
4. Login as Vendor1 (portal user):
   - Can access `/my/consign`.
   - Can see product A in picker; cannot see product B.
   - Add product A qty 5; cart displays the line.
   - Update qty and remove line (set qty to 0) works.
   - Submit requires at least one line.
5. After submit:
   - RFQ appears in `/my/consign/rfqs`.
   - Detail is read-only; cart routes no longer allow editing submitted RFQ.
6. Internal user:
   - Purchase app shows draft PO with `x_portal_rfq = True` and order lines.
   - Search filters **Portal RFQs** and **Portal Submitted** work.
   - Purchase manager activities are created on submission.
7. Security:
   - Portal user cannot access other purchase orders by guessing IDs.

## Notes

- `price_unit` is set to `0.0` for portal-added lines, so internal purchasing can set final pricing later.
- Module is designed for Odoo 18.0 and kept compatible with nearby versions where possible.
