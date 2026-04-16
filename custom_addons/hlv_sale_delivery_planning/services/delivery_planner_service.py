from odoo import models, api
from markupsafe import Markup
import re

_SKIP_MSG_RE = re.compile(
    r'Lệnh chuyển hàng được tạo'
    r'|lệnh chuyển hàng đã được tạo ra từ'
    r'|Đồng bộ \(xoá .{0,5} tạo lại\) thành công'
    r'|This transfer has been created from'
    r'|Transfer created'
    r'|Sales Order created'
    r'|Quotation created'
    r'|has been created from'
    r'|Đơn hàng được tạo',
    re.IGNORECASE
)


class DeliveryPlannerService(models.AbstractModel):
    _name = 'hlv.delivery.planner.service'
    _description = 'Delivery Planner Dashboard Service'

    @api.model
    def get_dashboard_data(
        self,
        search_query='', filter_warehouse_id='all',
        filter_delivery_status='all', filter_stock_status='all',
        filter_packing_status='all', filter_date_from='', filter_date_to='',
        filter_po_date_from='', filter_po_date_to='', filter_po_status='all',
        filter_done_date_from='', filter_done_date_to='',
        limit=12, offset=0, filter_saler_code='',
        filter_htgh='', filter_delivery_type='all', filter_tag_ids='',
        show_completed=False, filter_need_transfer=False,        filter_new_orders=False,    ):

        domain = self._build_search_domain(
            search_query, filter_warehouse_id,
            filter_delivery_status, filter_date_from, filter_date_to,
            filter_saler_code=filter_saler_code,
            filter_htgh=filter_htgh,
            filter_delivery_type=filter_delivery_type,
            filter_tag_ids=filter_tag_ids,
        )
        sales = self.env['sale.order'].search(
            domain,
            order='x_studio_misa_order_date desc nulls last, create_date desc, commitment_date asc, date_order desc'
        )

        sales, matched_ids, dashboard_stats, product_availabilities, so_status_dict = \
            self._calculate_po_and_stock_status(
                sales, filter_po_date_from, filter_po_date_to,
                filter_po_status, filter_delivery_status, filter_stock_status, filter_packing_status,
                show_completed=show_completed,
                filter_need_transfer=filter_need_transfer,
                filter_new_orders=filter_new_orders,
                filter_done_date_from=filter_done_date_from,
                filter_done_date_to=filter_done_date_to,
            )

        total_count = len(matched_ids)
        page_sales = self.env['sale.order'].browse(
            matched_ids[int(offset): int(offset) + int(limit)]
        )

        po_by_origin = self._fetch_pos_for_sales(page_sales)
        att_by_picking = self._fetch_attachments_for_pickings(page_sales.mapped('picking_ids').ids)
        so_packages_dict = self._fetch_packages_for_sales(page_sales)

        # Fix High #2: batch compute transfer suggestions ONCE for all page SOs
        # Thay vì _compute_transfer_suggestions per-SO (N×M×P queries),
        # dùng 1 location + 1 quant + 1 moves query cho toàn trang.
        transfer_map = self._batch_transfer_suggestions(page_sales, product_availabilities)

        result = [
            self._format_dashboard_order(
                so, po_by_origin, product_availabilities,
                att_by_picking, so_packages_dict, so_status_dict.get(so.id, {}),
                transfer_suggestions=transfer_map.get(so.id),
            )
            for so in page_sales
        ]
        warehouses = self.env['stock.warehouse'].search_read([], ['id', 'name'])
        tags = self.env['crm.tag'].search_read([], ['id', 'name'])

        return {
            'orders': result,
            'warehouses': warehouses,
            'tags': tags,
            'total_count': total_count,
            'dashboard_stats': dashboard_stats,
        }

    @api.model
    def get_order_messages(self, order_id):
        so = self.env['sale.order'].browse(int(order_id))
        if not so.exists():
            return []
            
        # Đánh dấu là đã đọc khi Internal User bấm xem tin nhắn
        if getattr(so, 'x_plan_unread_message', False):
            so.sudo().write({'x_plan_unread_message': False})
            
        picking_ids = so.picking_ids.ids
        domain = [
            '|',
            '&', ('model', '=', 'sale.order'), ('res_id', '=', so.id),
            '&', ('model', '=', 'stock.picking'), ('res_id', 'in', picking_ids),
        ]
        messages = self.env['mail.message'].search(domain, order='date desc', limit=200)
        picking_name_map = {p.id: p.name for p in so.picking_ids}
        result = []
        for msg in messages:
            plain = re.sub(r'<[^>]+>', '', msg.body or '').strip()
            has_att = bool(msg.attachment_ids)
            if not plain and not has_att:
                continue
            if plain and _SKIP_MSG_RE.search(plain):
                continue
            attachments = [{
                'id': att.id, 'name': att.name or '',
                'mimetype': att.mimetype or 'application/octet-stream',
                'file_size': att.file_size or 0,
            } for att in msg.attachment_ids]
            origin = ''
            if msg.model == 'stock.picking':
                origin = picking_name_map.get(msg.res_id, '')
            result.append({
                'id': msg.id,
                'date': msg.date.strftime('%d/%m/%Y %H:%M') if msg.date else '',
                'author': msg.author_id.name if msg.author_id else (msg.email_from or ''),
                'body': msg.body or '',
                'origin': origin,
                'attachments': attachments,
            })
        return result

    @api.model
    def post_order_message(self, order_id, body):
        so = self.env['sale.order'].browse(int(order_id))
        if not so.exists():
            return False
        safe_body = Markup('<p>%s</p>') % Markup.escape(body)
        so.message_post(
            body=safe_body,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
        return True

    @api.model
    def _batch_transfer_suggestions(self, page_sales, product_availabilities):
        """
        Batch version: tính transfer_suggestions cho toàn trang trong 1-2 queries
        thay vì N × M × P queries của _compute_transfer_suggestions per-SO.
        Trả về: {so_id: [{product_id, product_name, shortage, to_warehouse_name, sources}]}
        """
        if not page_sales:
            return {}

        # Bước 1: Xác định shortage per SO từ product_availabilities đã có
        all_tmpl_ids = page_sales.mapped('order_line.product_id.product_tmpl_id').ids
        kits = self.env['mrp.bom'].sudo().search([
            ('product_tmpl_id', 'in', all_tmpl_ids), ('type', '=', 'phantom'),
        ]) if all_tmpl_ids else self.env['mrp.bom']
        kit_tmpl_ids = set(kits.mapped('product_tmpl_id').ids)

        so_shortages = {}    # {so_id: [{pid, pname, shortage}]}
        dest_wh_by_so = {}   # {so_id: warehouse_id}
        shortage_prod_ids = set()

        for so in page_sales:
            if not so.warehouse_id:
                continue
            dest_wh_id = so.warehouse_id.id
            dest_wh_by_so[so.id] = dest_wh_id

            active_pks = so.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel') and not p.return_id
            )
            products_with_demand = {
                mv.product_id.id
                for pk in active_pks
                for mv in pk.move_ids
                if mv.state not in ('cancel', 'done')
            }
            line_reserved = {}
            for mv in active_pks.mapped('move_ids').filtered(
                lambda m: m.state not in ('cancel', 'done')
            ):
                lid = mv.sale_line_id.id
                if lid:
                    line_reserved[lid] = line_reserved.get(lid, 0.0) + mv.quantity

            shortages = []
            for line in so.order_line:
                if line.display_type or not line.product_id:
                    continue
                if line.product_id.type == 'service':
                    continue
                if line.product_id.product_tmpl_id.id in kit_tmpl_ids:
                    continue
                pid = line.product_id.id
                if pid not in products_with_demand:
                    continue
                pending = line.product_uom_qty - line.qty_delivered
                if pending <= 0:
                    continue
                avail = (product_availabilities.get((pid, dest_wh_id), 0.0)
                         + line_reserved.get(line.id, 0.0))
                if pending - avail > 0:
                    shortages.append({
                        'product_id': pid,
                        'product_name': line.product_id.display_name,
                        'shortage': pending - avail,
                    })
                    shortage_prod_ids.add(pid)
            if shortages:
                so_shortages[so.id] = shortages

        if not so_shortages:
            return {}

        # Bước 2: Kho khác (ngoài các kho đích của trang)
        all_dest_wh_ids = set(dest_wh_by_so.values())
        other_whs = self.env['stock.warehouse'].search([('id', 'not in', list(all_dest_wh_ids))])
        if not other_whs:
            return {}

        # Bước 3: Load availability tại other warehouses
        # Nếu product_availabilities đã có (vì filter_need_transfer=True), dùng trực tiếp
        other_avail = {}
        missing_keys = set()
        for pid in shortage_prod_ids:
            for wh in other_whs:
                key = (pid, wh.id)
                if key in product_availabilities:
                    other_avail[key] = product_availabilities[key]
                else:
                    missing_keys.add(key)

        if missing_keys:
            needed_wh_ids = list({k[1] for k in missing_keys})
            needed_prod_ids = list({k[0] for k in missing_keys})
            needed_whs = self.env['stock.warehouse'].browse(needed_wh_ids)
            root_loc_ids = [wh.lot_stock_id.id for wh in needed_whs if wh.lot_stock_id]

            if root_loc_ids:
                child_locs = self.env['stock.location'].sudo().search([
                    ('id', 'child_of', root_loc_ids), ('usage', '=', 'internal'),
                ])
                loc_to_owh = {}
                for wh in needed_whs:
                    if not wh.lot_stock_id:
                        continue
                    for loc in child_locs:
                        if loc.parent_path and f'/{wh.lot_stock_id.id}/' in loc.parent_path:
                            if loc.id not in loc_to_owh:
                                loc_to_owh[loc.id] = wh.id

                if loc_to_owh:
                    # ONE quant query
                    q_rows = self.env['stock.quant'].sudo().read_group(
                        domain=[
                            ('product_id', 'in', needed_prod_ids),
                            ('location_id', 'in', list(loc_to_owh.keys())),
                        ],
                        fields=['product_id', 'location_id', 'quantity:sum', 'reserved_quantity:sum'],
                        groupby=['product_id', 'location_id'],
                    )
                    for row in q_rows:
                        pid = row['product_id'][0]
                        wh_id = loc_to_owh.get(row['location_id'][0])
                        if wh_id:
                            free = max(
                                (row.get('quantity') or 0.0) - (row.get('reserved_quantity') or 0.0), 0.0
                            )
                            key = (pid, wh_id)
                            other_avail[key] = other_avail.get(key, 0.0) + free

                    # ONE internal moves query
                    int_moves = self.env['stock.move'].sudo().search_read([
                        ('product_id', 'in', needed_prod_ids),
                        ('state', 'in', ('assigned', 'partially_available')),
                        ('picking_id.picking_type_code', '=', 'internal'),
                        ('picking_id.state', 'not in', ('done', 'cancel')),
                        ('sale_line_id', '=', False),
                        ('location_id', 'in', list(loc_to_owh.keys())),
                    ], ['product_id', 'location_id', 'quantity'])
                    for mv in int_moves:
                        pid = mv['product_id'][0]
                        wh_id = loc_to_owh.get(mv['location_id'][0])
                        if wh_id:
                            key = (pid, wh_id)
                            other_avail[key] = other_avail.get(key, 0.0) + mv['quantity']

        # Bước 4: Build kết quả per SO
        wh_name = {wh.id: wh.name for wh in other_whs}
        so_wh_name = {so.id: so.warehouse_id.name for so in page_sales if so.warehouse_id}
        result = {}
        for so_id, shortages in so_shortages.items():
            suggestions = []
            for sp in shortages:
                pid, remaining = sp['product_id'], sp['shortage']
                sources = []
                for wh in other_whs:
                    if remaining <= 0:
                        break
                    available = other_avail.get((pid, wh.id), 0.0)
                    if available > 0:
                        suggest_qty = min(available, remaining)
                        sources.append({
                            'from_warehouse_id': wh.id,
                            'from_warehouse_name': wh_name.get(wh.id, ''),
                            'available_qty': available,
                            'suggested_qty': suggest_qty,
                            'blocking_pickings': [],
                        })
                        remaining -= suggest_qty
                if sources:
                    suggestions.append({
                        'product_id': pid,
                        'product_name': sp['product_name'],
                        'shortage': sp['shortage'],
                        'to_warehouse_name': so_wh_name.get(so_id, ''),
                        'sources': sources,
                    })
            if suggestions:
                result[so_id] = suggestions
        return result
