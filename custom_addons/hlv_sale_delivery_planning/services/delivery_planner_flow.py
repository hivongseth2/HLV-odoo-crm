from odoo import models


class DeliveryPlannerServiceFlow(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    def _build_flow_nodes(self, so, att_by_picking):
        """
        Xây dựng cây luồng xử lý kho (flows) cho một SO:
        - Mỗi "flow" là một tuyến độc lập (outbound hoặc return).
        - Các node trong flow được sắp xếp theo chuỗi move gốc → đích.
        """
        all_so_pickings = so.picking_ids

        # --- Phân loại picking: return và storage ---
        return_ps_dict = {}   # {src_picking_id: [return_picking, ...]}
        stor_ps_dict = {}     # {return_picking_id: [storage_picking, ...]}
        branch_ids = set()

        for p in all_so_pickings:
            if hasattr(p, 'return_ids') and p.return_ids:
                for rp in p.return_ids.filtered(lambda x: x in all_so_pickings):
                    return_ps_dict.setdefault(p.id, []).append(rp)
                    branch_ids.add(rp.id)
            else:
                for rp in all_so_pickings.filtered(
                    lambda x: hasattr(x, 'return_id') and x.return_id.id == p.id
                ):
                    return_ps_dict.setdefault(p.id, []).append(rp)
                    branch_ids.add(rp.id)

        for rp_list in return_ps_dict.values():
            for rp in rp_list:
                for stor in rp.move_ids.move_dest_ids.picking_id.filtered(
                    lambda x: x in all_so_pickings
                ):
                    stor_ps_dict.setdefault(rp.id, []).append(stor)
                    branch_ids.add(stor.id)

        # --- Xác định root pickings cho các luồng xuất và trả ---
        all_returns_and_stors = set()
        return_roots = set()
        for rp_list in return_ps_dict.values():
            for rp in rp_list:
                return_roots.add(rp)
                all_returns_and_stors.add(rp)
        for stor_list in stor_ps_dict.values():
            for stor in stor_list:
                all_returns_and_stors.add(stor)

        main_roots = all_so_pickings.filtered(
            lambda x: x not in all_returns_and_stors
            and not any(
                m.picking_id in all_so_pickings
                and m.picking_id not in all_returns_and_stors
                and m.picking_id != x
                for m in x.move_ids.mapped('move_orig_ids')
            )
        )

        # --- Đánh số thứ tự thời gian toàn cục cho các phiếu ---
        sorted_done = sorted(
            all_so_pickings.filtered(lambda p: p.state == 'done' and p.date_done),
            key=lambda p: p.date_done,
        )
        sorted_pending = sorted(
            all_so_pickings.filtered(lambda p: p.state != 'done'),
            key=lambda p: p.scheduled_date or p.create_date,
        )
        picking_seq_map = {
            p.id: idx + 1
            for idx, p in enumerate(sorted_done + sorted_pending)
        }

        # --- Helper: build danh sách node từ danh sách picking ---
        def build_path_nodes(path_pickings):
            return [
                {
                    'id': p.id, 'name': p.name, 'state': p.state,
                    'type_name': p.picking_type_id.name or '',
                    'code': p.picking_type_id.code or '',
                    'global_seq': picking_seq_map.get(p.id, 0),
                    'scheduled_date': p.scheduled_date.strftime('%Y-%m-%d') if p.scheduled_date else False,
                    'backorder_of': p.backorder_id.name if p.backorder_id else False,
                    'return_of': p.return_id.name if hasattr(p, 'return_id') and p.return_id else False,
                    'printed': bool(getattr(p, 'x_printed', False)),
                    'bien_ban_printed': bool(getattr(p, 'x_bien_ban_printed', False)),
                    'videos': att_by_picking.get(p.id, []),
                }
                for p in path_pickings
            ]

        # --- Helper: duyệt đệ quy theo move_dest_ids để tìm tất cả path ---
        def get_paths(picking, allowed_pickings, visited=None):
            if visited is None:
                visited = set()

            # Chặn vòng lặp khi chain move tạo cycle bất thường.
            if picking.id in visited:
                return [[picking]]

            next_visited = set(visited)
            next_visited.add(picking.id)
            next_pickings = picking.move_ids.mapped('move_dest_ids.picking_id').filtered(
                lambda x: x in allowed_pickings and x.id != picking.id and x.id not in next_visited
            )
            if not next_pickings:
                return [[picking]]
            paths = []
            for np in next_pickings:
                for sub_path in get_paths(np, allowed_pickings, next_visited):
                    if picking not in sub_path:
                        paths.append([picking] + sub_path)
            return paths if paths else [[picking]]

        # --- Build flows xuất (outbound) ---
        flows = []
        path_counter = 1
        all_returns = self.env['stock.picking'].browse([p.id for p in all_returns_and_stors])
        outbound_allowed = all_so_pickings - all_returns

        for root in sorted(main_roots, key=lambda x: (x.scheduled_date or x.create_date, x.id)):
            for path in get_paths(root, outbound_allowed):
                flows.append({
                    'id': f'path_{so.id}_{path_counter}',
                    'is_return': False,
                    'nodes': build_path_nodes(path),
                })
                path_counter += 1

        # --- Build flows trả (return) ---
        for root in sorted(list(return_roots), key=lambda x: (x.scheduled_date or x.create_date, x.id)):
            for path in get_paths(root, all_returns_and_stors):
                flows.append({
                    'id': f'path_{so.id}_{path_counter}',
                    'is_return': True,
                    'nodes': build_path_nodes(path),
                })
                path_counter += 1

        return flows
