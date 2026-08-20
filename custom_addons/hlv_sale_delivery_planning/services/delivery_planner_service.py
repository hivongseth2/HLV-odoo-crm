"""Main delivery planner dashboard orchestration service.

This file coordinates the dashboard list request: it builds the candidate sale
orders, chooses the snapshot fast path when possible, formats the visible page,
and falls back to the full realtime status pipeline whenever snapshots are not
clean enough to trust.
"""

from odoo import models, api


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
        domain=None, include_stats=True, filter_mine=False,
    ):

        search_domain = self._build_search_domain(
            search_query, filter_warehouse_id,
            filter_delivery_status, filter_date_from, filter_date_to,
            filter_saler_code=filter_saler_code,
            filter_htgh=filter_htgh,
            filter_delivery_type=filter_delivery_type,
            filter_tag_ids=filter_tag_ids,
            filter_mine=filter_mine,
        )
        if domain:
            extra_domain = list(domain)
            search_domain = search_domain + extra_domain
        sales = self.env['sale.order'].search(
            search_domain,
            order='x_studio_misa_order_date desc nulls last, create_date desc, commitment_date asc, date_order desc'
        )

        snapshot_match = None
        if self._can_use_snapshot_dashboard_match(
            filter_po_date_from=filter_po_date_from,
            filter_po_date_to=filter_po_date_to,
            filter_po_status=filter_po_status,
            filter_done_date_from=filter_done_date_from,
            filter_done_date_to=filter_done_date_to,
            filter_need_transfer=filter_need_transfer,
            domain=domain,
        ):
            snapshot_match = self._get_snapshot_dashboard_match(
                sales,
                filter_delivery_status=filter_delivery_status,
                filter_stock_status=filter_stock_status,
                filter_packing_status=filter_packing_status,
                show_completed=show_completed,
                filter_new_orders=filter_new_orders,
                filter_print_status=filter_print_status,
                filter_shipper_received=filter_shipper_received,
            )

        if snapshot_match:
            matched_ids = snapshot_match['matched_ids']
            dashboard_stats = snapshot_match['dashboard_stats']
            page_sales = self.env['sale.order'].browse(
                matched_ids[int(offset): int(offset) + int(limit)]
            )
            page_sales, _page_ids, _stats, product_availabilities, product_on_hand, so_status_dict = \
                self._calculate_po_and_stock_status(
                    page_sales, filter_po_date_from, filter_po_date_to,
                    filter_po_status, filter_delivery_status, filter_stock_status,
                    filter_packing_status,
                    show_completed=True,
                    filter_need_transfer=False,
                    filter_new_orders=False,
                    filter_done_date_from='',
                    filter_done_date_to='',
                    filter_print_status='all',
                    filter_shipper_received='all',
                )
        else:
            sales, matched_ids, dashboard_stats, product_availabilities, product_on_hand, so_status_dict = \
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
            page_sales = self.env['sale.order'].browse(
                matched_ids[int(offset): int(offset) + int(limit)]
            )

        total_count = len(matched_ids)

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
        page_kit_bom_map = {'by_product': {}, 'by_template': {}}
        for bom in page_kits:
            if bom.product_id:
                page_kit_bom_map['by_product'][bom.product_id.id] = bom
            else:
                page_kit_bom_map['by_template'].setdefault(bom.product_tmpl_id.id, bom)

        # Batch load blocking moves cho tất cả 12 SO trang (thay thế 12× stock.move.search per-SO)
        # Chỉ load khi có kho, gom theo (so_id, product_id)
        page_blocking_by_so = self._batch_blocking_moves(page_sales)

        # Fix High #2: batch compute transfer suggestions ONCE for all page SOs
        # Thay vì tính transfer suggestions per-SO (N×M×P queries),
        # dùng 1 location + 1 quant + 1 moves query cho toàn trang.
        transfer_map = self._batch_transfer_suggestions(page_sales, product_availabilities)

        # Batch tồn kho khả dụng của component Kit cho TOÀN TRANG — thay vì mỗi đơn tự tính
        # lại (1 location search + 1 quant read_group), lặp lại N lần cùng 1 kết quả nếu N đơn
        # cùng kho. Đo thực tế: đây là bước tốn nhất trong _format_dashboard_order (~3.2s/6.2s
        # cho 372 đơn cùng kho, xem bin/profile_format_dashboard_order.py).
        page_kit_comp_free = self._batch_kit_component_free_stock(page_sales, page_kit_bom_map)

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
                so, po_by_origin, product_availabilities, product_on_hand,
                att_by_picking, so_packages_dict, so_status_dict.get(so.id, {}),
                transfer_suggestions=transfer_map.get(so.id, []),
                page_kit_tmpl_ids=page_kit_tmpl_ids,
                page_kit_bom_map=page_kit_bom_map,
                page_blocking_by_so=page_blocking_by_so,
                page_kit_comp_free=page_kit_comp_free,
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
            filter_mine=filter_mine,
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
    def _can_use_snapshot_dashboard_match(
        self, filter_po_date_from='', filter_po_date_to='', filter_po_status='all',
        filter_done_date_from='', filter_done_date_to='',
        filter_need_transfer=False, domain=None,
    ):
        if domain:
            return False
        if filter_need_transfer:
            return False
        if filter_done_date_from or filter_done_date_to:
            return False
        if filter_po_date_from or filter_po_date_to:
            return False
        if filter_po_status and filter_po_status != 'all':
            return False
        return True

    @api.model
    def get_orders_subset(self, order_ids, filter_kwargs=None):
        """Lightweight partial refresh used by the bus update flow.

        Re-formats only the given sale.order ids using the same Phase 1+2
        batch loaders, but scoped to those ids — avoids the heavy work over
        the whole filtered set. Returns a list of formatted orders the
        frontend can merge into its existing state.

        Khi `filter_kwargs` được truyền vào (frontend đẩy nguyên bộ lọc hiện
        tại của user), backend sẽ chạy lại đúng search_domain + status compute
        trên subset. Các SO không khớp filter sẽ rơi vào `removed_ids`, FE
        dựa vào đó để bỏ qua (không add vào kanban) hoặc remove khỏi state
        nếu đang hiển thị. Tránh trường hợp bus đẩy 1 SO kho A vào dashboard
        đang lọc kho B.

        Returns:
            {
                'orders': [...],   # formatted orders for ids that still exist
                'removed_ids': [], # ids that no longer exist or don't match filters
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

        fk = filter_kwargs or {}

        # Khi FE truyền filter_kwargs: chạy lại search_domain trên subset để
        # loại bớt các SO không match SQL-level filters (warehouse, ngày, htgh,
        # delivery_type, tag, search_query, ...).
        if fk:
            search_domain = self._build_search_domain(
                fk.get('search_query', ''),
                fk.get('filter_warehouse_id', 'all'),
                fk.get('filter_delivery_status', 'all'),
                fk.get('filter_date_from', ''),
                fk.get('filter_date_to', ''),
                filter_saler_code=fk.get('filter_saler_code', ''),
                filter_htgh=fk.get('filter_htgh', ''),
                filter_delivery_type=fk.get('filter_delivery_type', 'all'),
                filter_tag_ids=fk.get('filter_tag_ids', ''),
                filter_mine=fk.get('filter_mine', False),
            )
            search_domain = [('id', 'in', list(existing_ids))] + search_domain
            page_sales = self.env['sale.order'].search(search_domain)
            kept = set(page_sales.ids)
            for i in existing_ids:
                if i not in kept:
                    removed_ids.append(i)
            if not page_sales:
                return {'orders': [], 'removed_ids': removed_ids}

        # Run the same batch status compute, but only over the subset.
        # Khi không có filter_kwargs (legacy callers): giữ nguyên hành vi cũ
        # (show_completed=True, không filter status) — chỉ refresh data.
        if fk:
            page_sales, _matched_ids, _stats, product_availabilities, product_on_hand, so_status_dict = \
                self._calculate_po_and_stock_status(
                    page_sales,
                    fk.get('filter_po_date_from', ''),
                    fk.get('filter_po_date_to', ''),
                    fk.get('filter_po_status', 'all'),
                    fk.get('filter_delivery_status', 'all'),
                    fk.get('filter_stock_status', 'all'),
                    fk.get('filter_packing_status', 'all'),
                    show_completed=fk.get('show_completed', False),
                    filter_need_transfer=fk.get('filter_need_transfer', False),
                    filter_new_orders=fk.get('filter_new_orders', False),
                    filter_done_date_from=fk.get('filter_done_date_from', ''),
                    filter_done_date_to=fk.get('filter_done_date_to', ''),
                    filter_print_status=fk.get('filter_print_status', 'all'),
                    filter_shipper_received=fk.get('filter_shipper_received', 'all'),
                )
            kept_py = set(page_sales.ids)
            for i in existing_ids:
                if i not in kept_py and i not in removed_ids:
                    removed_ids.append(i)
            if not page_sales:
                return {'orders': [], 'removed_ids': removed_ids}
        else:
            page_sales, _matched_ids, _stats, product_availabilities, product_on_hand, so_status_dict = \
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
        page_kit_bom_map = {'by_product': {}, 'by_template': {}}
        for bom in page_kits:
            if bom.product_id:
                page_kit_bom_map['by_product'][bom.product_id.id] = bom
            else:
                page_kit_bom_map['by_template'].setdefault(bom.product_tmpl_id.id, bom)

        page_blocking_by_so = self._batch_blocking_moves(page_sales)
        transfer_map = self._batch_transfer_suggestions(page_sales, product_availabilities)
        page_kit_comp_free = self._batch_kit_component_free_stock(page_sales, page_kit_bom_map)

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
                so, po_by_origin, product_availabilities, product_on_hand,
                att_by_picking, so_packages_dict, so_status_dict.get(so.id, {}),
                transfer_suggestions=transfer_map.get(so.id, []),
                page_kit_tmpl_ids=page_kit_tmpl_ids,
                page_kit_bom_map=page_kit_bom_map,
                page_blocking_by_so=page_blocking_by_so,
                page_kit_comp_free=page_kit_comp_free,
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
