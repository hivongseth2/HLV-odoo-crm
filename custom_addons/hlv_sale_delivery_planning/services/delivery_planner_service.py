import os

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

_ALLOWED_CHAT_ATTACHMENT_MIMES = {
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/csv',
}
_ALLOWED_CHAT_ATTACHMENT_EXTS = {'.doc', '.docx', '.xls', '.xlsx', '.csv'}
_MAX_CHAT_ATTACHMENT_BYTES = 20 * 1024 * 1024


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
        show_completed=False, filter_need_transfer=False, filter_new_orders=False,
        filter_print_status='all', filter_shipper_received='all',
        domain=None, include_stats=True,
    ):

        search_domain = self._build_search_domain(
            search_query, filter_warehouse_id,
            filter_delivery_status, filter_date_from, filter_date_to,
            filter_saler_code=filter_saler_code,
            filter_htgh=filter_htgh,
            filter_delivery_type=filter_delivery_type,
            filter_tag_ids=filter_tag_ids,
        )
        if domain:
            extra_domain = list(domain)
            search_domain = search_domain + extra_domain
        sales = self.env['sale.order'].search(
            search_domain,
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
                filter_print_status=filter_print_status,
                filter_shipper_received=filter_shipper_received,
            )

        total_count = len(matched_ids)
        page_sales = self.env['sale.order'].browse(
            matched_ids[int(offset): int(offset) + int(limit)]
        )

        po_by_origin = self._fetch_pos_for_sales(page_sales)
        att_by_picking = self._fetch_attachments_for_pickings(page_sales.mapped('picking_ids').ids)
        so_packages_dict = self._fetch_packages_for_sales(page_sales)

        # Batch load BOM kits cho tất cả 12 SO trang (thay thế 12× mrp.bom.search per-SO)
        page_tmpl_ids = page_sales.mapped('order_line.product_id.product_tmpl_id').ids
        page_kits = self.env['mrp.bom'].sudo().search([
            ('product_tmpl_id', 'in', page_tmpl_ids), ('type', '=', 'phantom'),
        ]) if page_tmpl_ids else self.env['mrp.bom']
        page_kit_tmpl_ids = set(page_kits.mapped('product_tmpl_id').ids)
        # Kit BOM map: {tmpl_id: bom} để tra nhanh
        page_kit_bom_map = {bom.product_tmpl_id.id: bom for bom in page_kits}

        # Batch load blocking moves cho tất cả 12 SO trang (thay thế 12× stock.move.search per-SO)
        # Chỉ load khi có kho, gom theo (so_id, product_id)
        page_blocking_by_so = self._batch_blocking_moves(page_sales)

        # Fix High #2: batch compute transfer suggestions ONCE for all page SOs
        # Thay vì _compute_transfer_suggestions per-SO (N×M×P queries),
        # dùng 1 location + 1 quant + 1 moves query cho toàn trang.
        transfer_map = self._batch_transfer_suggestions(page_sales, product_availabilities)

        # Optimization: pre-warm prefetch cache for picking graph used by _build_flow_nodes.
        # Without this, each per-SO call to _build_flow_nodes triggers many SQL round-trips
        # (move_dest_ids, move_orig_ids, picking_id, picking_type_id...) for that SO alone.
        # By traversing the WHOLE page's picking graph once, ORM prefetch fills the cache so
        # the 12× recursive calls become pure Python.
        # NOTE: With lazy flows (with_flows=False below), the per-page recursive calls are
        # skipped entirely, so we only do this prefetch when flows are actually built.
        # Keeping the helper guarded behind get_so_flow() / explicit with_flows callers.
        page_pickings = page_sales.mapped('picking_ids')
        # Prefetch only when caller will actually walk the picking graph.
        # (Lazy flow path: skipped entirely → ~40-60% CPU savings per page.)
        _prefetch_flow_graph = False
        if _prefetch_flow_graph and page_pickings:
            page_pickings.read([
                'state', 'date_done', 'scheduled_date', 'create_date',
                'picking_type_id', 'backorder_id', 'return_id',
                'move_ids',
            ])
            all_moves = page_pickings.mapped('move_ids')
            if all_moves:
                all_moves.read(['picking_id', 'move_dest_ids', 'move_orig_ids'])
                # Touch dest/orig to prefetch their picking_id in one go
                (all_moves.move_dest_ids | all_moves.move_orig_ids).read(['picking_id'])
            page_pickings.picking_type_id.read(['name', 'code'])

        result = [
            self._format_dashboard_order(
                so, po_by_origin, product_availabilities,
                att_by_picking, so_packages_dict, so_status_dict.get(so.id, {}),
                transfer_suggestions=transfer_map.get(so.id),
                page_kit_tmpl_ids=page_kit_tmpl_ids,
                page_kit_bom_map=page_kit_bom_map,
                page_blocking_by_so=page_blocking_by_so,
            )
            for so in page_sales
        ]
        warehouses = self.env['stock.warehouse'].search_read([], ['id', 'name'])
        tags = self.env['crm.tag'].search_read([], ['id', 'name'])

        # Populate stats cache so subsequent get_dashboard_stats_only calls
        # (e.g. parallel KPI prefetch on next page load) hit warm.
        self._store_stats_cache(
            dashboard_stats, total_count,
            search_query=search_query, filter_warehouse_id=filter_warehouse_id,
            filter_delivery_status=filter_delivery_status,
            filter_stock_status=filter_stock_status,
            filter_packing_status=filter_packing_status,
            filter_date_from=filter_date_from, filter_date_to=filter_date_to,
            filter_po_date_from=filter_po_date_from,
            filter_po_date_to=filter_po_date_to,
            filter_po_status=filter_po_status,
            filter_done_date_from=filter_done_date_from,
            filter_done_date_to=filter_done_date_to,
            filter_saler_code=filter_saler_code, filter_htgh=filter_htgh,
            filter_delivery_type=filter_delivery_type,
            filter_tag_ids=filter_tag_ids,
            show_completed=show_completed,
            filter_need_transfer=filter_need_transfer,
            filter_new_orders=filter_new_orders,
            filter_print_status=filter_print_status,
            filter_shipper_received=filter_shipper_received,
            domain=domain,
        )

        return {
            'orders': result,
            'warehouses': warehouses,
            'tags': tags,
            'total_count': total_count,
            # Stats are loaded asynchronously by the frontend via
            # get_dashboard_stats_only, so omit them when include_stats is
            # False to keep the response payload light and signal to the
            # client that it should not overwrite existing KPI values.
            'dashboard_stats': dashboard_stats if include_stats else None,
        }

    @api.model
    def get_orders_subset(self, order_ids):
        """Lightweight partial refresh used by the bus update flow.

        Re-formats only the given sale.order ids using the same Phase 1+2
        batch loaders, but scoped to those ids — avoids the heavy work over
        the whole filtered set. Returns a list of formatted orders the
        frontend can merge into its existing state.

        Returns:
            {
                'orders': [...],   # formatted orders for ids that still exist
                'removed_ids': [], # ids that no longer exist or were cancelled
            }
        """
        if not order_ids:
            return {'orders': [], 'removed_ids': []}

        ids = [int(i) for i in order_ids if i]
        page_sales = self.env['sale.order'].browse(ids).exists()
        existing_ids = set(page_sales.ids)
        removed_ids = [i for i in ids if i not in existing_ids]

        if not page_sales:
            return {'orders': [], 'removed_ids': removed_ids}

        # Run the same batch status compute, but only over the subset.
        # All filters set to defaults — this endpoint just refreshes data,
        # filtering is the frontend's job (it can drop orders not matching).
        page_sales, _matched_ids, _stats, product_availabilities, so_status_dict = \
            self._calculate_po_and_stock_status(
                page_sales,
                po_date_from='', po_date_to='', po_status='all',
                filter_delivery_status='all', filter_stock_status='all',
                filter_packing_status='all',
                show_completed=True,  # never drop subset orders
                filter_need_transfer=False,
                filter_new_orders=False,
            )

        po_by_origin = self._fetch_pos_for_sales(page_sales)
        att_by_picking = self._fetch_attachments_for_pickings(page_sales.mapped('picking_ids').ids)
        so_packages_dict = self._fetch_packages_for_sales(page_sales)

        page_tmpl_ids = page_sales.mapped('order_line.product_id.product_tmpl_id').ids
        page_kits = self.env['mrp.bom'].sudo().search([
            ('product_tmpl_id', 'in', page_tmpl_ids), ('type', '=', 'phantom'),
        ]) if page_tmpl_ids else self.env['mrp.bom']
        page_kit_tmpl_ids = set(page_kits.mapped('product_tmpl_id').ids)
        page_kit_bom_map = {bom.product_tmpl_id.id: bom for bom in page_kits}

        page_blocking_by_so = self._batch_blocking_moves(page_sales)
        transfer_map = self._batch_transfer_suggestions(page_sales, product_availabilities)

        # Pre-warm prefetch for the picking graph (same as full load).
        # Subset is bus-driven (in-place card update); flows are loaded on
        # demand by the drawer, so skip the heavy graph walk here too.
        page_pickings = page_sales.mapped('picking_ids')
        _prefetch_flow_graph = False
        if _prefetch_flow_graph and page_pickings:
            page_pickings.read([
                'state', 'date_done', 'scheduled_date', 'create_date',
                'picking_type_id', 'backorder_id', 'return_id', 'move_ids',
            ])
            all_moves = page_pickings.mapped('move_ids')
            if all_moves:
                all_moves.read(['picking_id', 'move_dest_ids', 'move_orig_ids'])
                (all_moves.move_dest_ids | all_moves.move_orig_ids).read(['picking_id'])
            page_pickings.picking_type_id.read(['name', 'code'])

        orders = [
            self._format_dashboard_order(
                so, po_by_origin, product_availabilities,
                att_by_picking, so_packages_dict, so_status_dict.get(so.id, {}),
                transfer_suggestions=transfer_map.get(so.id),
                page_kit_tmpl_ids=page_kit_tmpl_ids,
                page_kit_bom_map=page_kit_bom_map,
                page_blocking_by_so=page_blocking_by_so,
            )
            for so in page_sales
        ]
        return {'orders': orders, 'removed_ids': removed_ids}

    @api.model
    def get_so_flow(self, so_id):
        """Lazy endpoint: build the picking graph (Luồng Xử Lý Kho) for a
        single sale.order on demand. Called by the frontend when the user
        expands the "Luồng Xử Lý Kho" section in the SO card. Removing this
        from the default dashboard payload cuts ~40-60% CPU per page load.

        Returns: {'flows': [...]} or {'flows': []} if SO not found.
        """
        if not so_id:
            return {'flows': []}
        so = self.env['sale.order'].browse(int(so_id)).exists()
        if not so:
            return {'flows': []}
        # Prefetch the picking graph for this SO so the recursive Python walk
        # is pure in-memory (no per-step SQL).
        pickings = so.picking_ids
        if pickings:
            pickings.read([
                'state', 'date_done', 'scheduled_date', 'create_date',
                'picking_type_id', 'backorder_id', 'return_id', 'move_ids',
            ])
            all_moves = pickings.mapped('move_ids')
            if all_moves:
                all_moves.read(['picking_id', 'move_dest_ids', 'move_orig_ids'])
                (all_moves.move_dest_ids | all_moves.move_orig_ids).read(['picking_id'])
            pickings.picking_type_id.read(['name', 'code'])
        att_by_picking = self._fetch_attachments_for_pickings(pickings.ids)
        flows = self._build_flow_nodes(so, att_by_picking)
        return {'flows': flows}

    @api.model
    def get_order_messages(self, order_id):
        so = self.env['sale.order'].browse(int(order_id))
        if not so.exists():
            return []
            
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
    def post_order_message(self, order_id, body='', attachments=None):
        so = self.env['sale.order'].browse(int(order_id))
        if not so.exists():
            return False

        body = (body or '').strip()
        attachments = attachments or []
        if not body and not attachments:
            return False

        attachment_ids = []
        for att in attachments:
            if not isinstance(att, dict):
                continue
            name = (att.get('name') or 'file').strip()[:255]
            mimetype = (att.get('mimetype') or 'application/octet-stream').strip().lower()
            datas = (att.get('datas') or '').strip()
            if not datas:
                continue
            if not self._is_allowed_chat_attachment(name, mimetype):
                continue
            estimated_size = int(len(datas) * 0.75)
            if estimated_size > _MAX_CHAT_ATTACHMENT_BYTES:
                continue
            new_att = self.env['ir.attachment'].sudo().create({
                'name': name,
                'datas': datas,
                'mimetype': mimetype or 'application/octet-stream',
                'res_model': 'sale.order',
                'res_id': so.id,
                'type': 'binary',
            })
            attachment_ids.append(new_att.id)

        if not body and not attachment_ids:
            return False

        safe_body = Markup('<p>%s</p>') % Markup.escape(body) if body else Markup('<p><i>Tệp đính kèm</i></p>')
        so.message_post(
            body=safe_body,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
            attachment_ids=attachment_ids,
        )
        return True

    @api.model
    def _is_allowed_chat_attachment(self, name, mimetype):
        if mimetype and (mimetype.startswith('image/') or mimetype.startswith('video/')):
            return True
        if mimetype in _ALLOWED_CHAT_ATTACHMENT_MIMES:
            return True
        ext = os.path.splitext(name or '')[1].lower()
        return ext in _ALLOWED_CHAT_ATTACHMENT_EXTS

    @api.model
    def _batch_blocking_moves(self, page_sales):
        """
        Batch load internal moves đang block hàng tại kho của từng SO trên trang.
        Thay 12× stock.move.search per-SO bằng 1 batch query.
        Trả về: {so_id: {product_id: [{picking_id, picking_name, ...}]}}
        """
        if not page_sales:
            return {}
        so_wh_locs = {}
        all_pending_pids = set()
        for so in page_sales:
            if not so.warehouse_id or not so.warehouse_id.lot_stock_id:
                continue
            so_wh_locs[so.id] = (so.warehouse_id.id, so.warehouse_id.lot_stock_id.id)
            for line in so.order_line:
                if line.display_type or not line.product_id:
                    continue
                if line.product_id.type == 'service':
                    continue
                if (line.product_uom_qty - line.qty_delivered) > 0:
                    all_pending_pids.add(line.product_id.id)

        if not all_pending_pids or not so_wh_locs:
            return {}

        all_root_locs = list({v[1] for v in so_wh_locs.values()})
        child_locs = self.env['stock.location'].sudo().search([
            ('id', 'child_of', all_root_locs), ('usage', '=', 'internal'),
        ])
        loc_to_whs = {}
        for so_id, (wh_id, root_loc) in so_wh_locs.items():
            for loc in child_locs:
                if loc.parent_path and f'/{root_loc}/' in loc.parent_path:
                    loc_to_whs.setdefault(loc.id, set()).add(wh_id)

        if not loc_to_whs:
            return {}

        raw_moves = self.env['stock.move'].sudo().search_read([
            ('product_id', 'in', list(all_pending_pids)),
            ('state', 'in', ('assigned', 'partially_available', 'confirmed', 'waiting')),
            ('location_id', 'in', list(loc_to_whs.keys())),
            ('picking_id', '!=', False),
            ('picking_id.state', 'not in', ('done', 'cancel')),
            ('sale_line_id', '=', False),
        ], ['product_id', 'location_id', 'quantity', 'picking_id'])

        pk_ids = list({mv['picking_id'][0] for mv in raw_moves if mv.get('picking_id')})
        pk_info = {}
        if pk_ids:
            for r in self.env['stock.picking'].sudo().search_read(
                [('id', 'in', pk_ids)],
                ['id', 'name', 'state', 'origin', 'picking_type_id'],
            ):
                pt_id = r['picking_type_id'][0] if r.get('picking_type_id') else None
                pk_info[r['id']] = {
                    'name': r['name'], 'state': r['state'],
                    'origin': r.get('origin') or '', 'pt_id': pt_id,
                }
            pt_ids = list({v['pt_id'] for v in pk_info.values() if v['pt_id']})
            if pt_ids:
                pt_map = {r['id']: r for r in self.env['stock.picking.type'].sudo().search_read(
                    [('id', 'in', pt_ids)], ['id', 'name', 'code'],
                )}
                for info in pk_info.values():
                    pt = pt_map.get(info['pt_id'], {})
                    info['type_name'] = pt.get('name') or ''
                    info['type_code'] = pt.get('code') or ''

        wh_to_sos = {}
        for so_id, (wh_id, _) in so_wh_locs.items():
            wh_to_sos.setdefault(wh_id, []).append(so_id)

        result = {}
        for mv in raw_moves:
            pid = mv['product_id'][0]
            qty = mv.get('quantity') or 0
            if qty <= 0:
                continue
            loc_id = mv['location_id'][0] if mv.get('location_id') else None
            pk_id = mv['picking_id'][0] if mv.get('picking_id') else None
            if not loc_id or not pk_id:
                continue
            pk_data = pk_info.get(pk_id, {})
            for wh_id in loc_to_whs.get(loc_id, set()):
                for so_id in wh_to_sos.get(wh_id, []):
                    entries = result.setdefault(so_id, {}).setdefault(pid, {})
                    if pk_id in entries:
                        entries[pk_id]['qty'] += qty
                    else:
                        entries[pk_id] = {
                            'picking_id': pk_id,
                            'picking_name': pk_data.get('name', ''),
                            'picking_type': pk_data.get('type_name', ''),
                            'picking_code': pk_data.get('type_code', ''),
                            'origin': pk_data.get('origin', ''),
                            'state': pk_data.get('state', ''),
                            'qty': qty,
                        }
        return {
            so_id: {pid: list(entries.values()) for pid, entries in by_prod.items()}
            for so_id, by_prod in result.items()
        }

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
                        fields=['quantity:sum', 'reserved_quantity:sum'],
                        groupby=['product_id', 'location_id'],
                    )
                    for row in q_rows:
                        pid_raw = row.get('product_id')
                        loc_raw = row.get('location_id')
                        if not pid_raw or not loc_raw:
                            continue
                        pid = pid_raw[0] if isinstance(pid_raw, (list, tuple)) else pid_raw
                        loc_id = loc_raw[0] if isinstance(loc_raw, (list, tuple)) else loc_raw
                        wh_id = loc_to_owh.get(loc_id)
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
