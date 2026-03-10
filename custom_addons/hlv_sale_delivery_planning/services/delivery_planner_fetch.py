import re
from odoo import models


class DeliveryPlannerServiceFetch(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    # ------------------------------------------------------------------
    # Purchase Orders
    # ------------------------------------------------------------------

    def _fetch_pos_for_sales(self, page_sales):
        """Lấy các PO liên quan đến danh sách SO theo trường origin."""
        sale_names = page_sales.mapped('name')
        all_pos = self.env['purchase.order'].search(
            [('origin', 'in', sale_names)]
        ) if sale_names else []

        po_by_origin = {}
        for po in all_pos:
            po_by_origin.setdefault(po.origin, []).append(po)
        return po_by_origin

    # ------------------------------------------------------------------
    # Attachments / Videos
    # ------------------------------------------------------------------

    def _fetch_attachments_for_pickings(self, all_picking_ids):
        """
        Tìm video đóng gói (file đính kèm hoặc log chatter) cho các phiếu kho.
        Trả về dict: {picking_id: [{id, name, url}, ...]}
        """
        att_by_picking = {}
        if not all_picking_ids:
            return att_by_picking

        # --- Attachments trực tiếp ---
        picking_attachments = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'stock.picking'),
            ('res_id', 'in', all_picking_ids),
        ])
        for att in picking_attachments:
            if att.name and (
                att.name.lower().endswith(('.webm', '.mp4'))
                or 'video' in (att.mimetype or '')
            ):
                att_by_picking.setdefault(att.res_id, []).append({
                    'id': att.id, 'name': att.name,
                    'url': f'/web/content/{att.id}?download=true',
                })

        # --- Video trong chatter (mail.message) ---
        messages = self.env['mail.message'].sudo().search([
            ('model', '=', 'stock.picking'),
            ('res_id', 'in', all_picking_ids),
        ])
        for msg in messages:
            if msg.attachment_ids:
                for att in msg.attachment_ids:
                    if att.name and (
                        att.name.lower().endswith(('.webm', '.mp4'))
                        or 'video' in (att.mimetype or '')
                    ):
                        url = f'/web/content/{att.id}?download=true'
                        if not any(a['url'] == url for a in att_by_picking.get(msg.res_id, [])):
                            att_by_picking.setdefault(msg.res_id, []).append(
                                {'id': att.id, 'name': att.name, 'url': url}
                            )

            if msg.body:
                if 'Video đóng gói' in msg.body or 'video' in msg.body.lower():
                    urls = re.findall(r'href=[\'"]([^\'"]+)[\'"]', msg.body)
                    for i, url in enumerate(urls):
                        clean_url = url.replace('&amp;', '&')
                        if not any(u['url'] == clean_url for u in att_by_picking.get(msg.res_id, [])):
                            att_by_picking.setdefault(msg.res_id, []).append({
                                'id': f"log_{msg.id}_{i}",
                                'name': 'Video Đóng Gói',
                                'url': clean_url,
                            })
                else:
                    urls = re.findall(r'(\/web\/content\/[0-9]+.*?\.webm)', msg.body)
                    for i, url in enumerate(urls):
                        clean_url = url.replace('&amp;', '&')
                        if not any(u['url'] == clean_url for u in att_by_picking.get(msg.res_id, [])):
                            att_by_picking.setdefault(msg.res_id, []).append({
                                'id': f"log_{msg.id}_{i}",
                                'name': 'Video Log',
                                'url': clean_url,
                            })

        return att_by_picking

    # ------------------------------------------------------------------
    # Packages
    # ------------------------------------------------------------------

    def _fetch_packages_for_sales(self, page_sales):
        """
        Lấy thông tin kiện hàng (stock.quant.package) theo từng phiếu kho
        của các SO, nhóm theo SO → Picking → Package.
        Trả về dict: {so_id: [{picking_id, picking_name, state, packages}, ...]}
        """
        all_picking_ids = page_sales.mapped('picking_ids').ids
        if not all_picking_ids:
            return {}

        move_lines = self.env['stock.move.line'].search_read([
            ('picking_id', 'in', all_picking_ids),
            ('result_package_id', '!=', False),
            ('state', '!=', 'cancel'),
        ], ['picking_id', 'result_package_id', 'product_id', 'quantity', 'location_dest_id'])

        if not move_lines:
            return {}

        # --- Lấy metadata kiện ---
        package_ids = list(set(
            ml['result_package_id'][0] for ml in move_lines if ml['result_package_id']
        ))
        packages = self.env['stock.quant.package'].sudo().browse(package_ids)
        pack_dict = {
            p.id: {
                'id': p.id,
                'name': p.name,
                'location_name': p.location_id.display_name if p.location_id else '',
                'pack_sequence': getattr(p, 'pack_sequence', 0),
                'pack_total': getattr(p, 'pack_total', 0),
            }
            for p in packages
        }

        # --- Thông tin picking ---
        pickings_objs = self.env['stock.picking'].sudo().browse(all_picking_ids)
        picking_info_map = {
            p.id: {'state': p.state, 'code': p.picking_type_id.code}
            for p in pickings_objs
        }
        picking_to_so = {
            picking.id: so.id
            for so in page_sales
            for picking in so.picking_ids
        }

        # --- Hàm ưu tiên loại phiếu (internal > outgoing > incoming) ---
        def picking_priority(ml):
            info = picking_info_map.get(ml['picking_id'][0], {})
            code = info.get('code', 'outgoing')
            return {'internal': 0, 'outgoing': 1, 'incoming': 2}.get(code, 9)

        sorted_move_lines = sorted(move_lines, key=picking_priority)

        # --- Gom nhóm SO → Picking → Package, khử trùng kiện theo tên ---
        so_picking_packs = {}
        package_seen_in_so = {}  # {so_id: {pname: first_pick_id}}

        for ml in sorted_move_lines:
            so_id = picking_to_so.get(ml['picking_id'][0])
            if not so_id:
                continue

            pname = ml['result_package_id'][1]
            package_seen_in_so.setdefault(so_id, {})

            if pname in package_seen_in_so[so_id]:
                if package_seen_in_so[so_id][pname] != ml['picking_id'][0]:
                    continue
            else:
                package_seen_in_so[so_id][pname] = ml['picking_id'][0]

            pick_id = ml['picking_id'][0]
            pick_name = ml['picking_id'][1]
            pid = ml['result_package_id'][0]

            so_picking_packs.setdefault(so_id, {})
            so_holding_packs = so_picking_packs[so_id]

            if pick_id not in so_holding_packs:
                info = picking_info_map.get(pick_id, {})
                so_holding_packs[pick_id] = {
                    'picking_id': pick_id,
                    'picking_name': pick_name,
                    'picking_state': info.get('state', 'unknown'),
                    'picking_code': info.get('code', 'outgoing'),
                    'packages_dict': {},
                }

            if pname not in so_picking_packs[so_id][pick_id]['packages_dict']:
                pack_info = pack_dict.get(pid, {
                    'id': pid, 'name': pname,
                    'location_name': '', 'pack_sequence': 0, 'pack_total': 0,
                })
                so_picking_packs[so_id][pick_id]['packages_dict'][pname] = {
                    'id': pid,
                    'name': pname,
                    'picking_id': pick_id,
                    'location_name': pack_info.get('location_name') or '',
                    'sequence': pack_info.get('pack_sequence') or 0,
                    'total': pack_info.get('pack_total') or 0,
                    'product_map': {},
                }

            p_content = so_picking_packs[so_id][pick_id]['packages_dict'][pname]
            prod_name = ml['product_id'][1] if ml['product_id'] else 'Unknown'
            qty = float(ml['quantity']) if ml.get('quantity') else 0.0
            p_content['product_map'][prod_name] = (
                p_content['product_map'].get(prod_name, 0.0) + qty
            )

        # --- Sắp xếp theo thứ tự phiếu kho trong SO và format kết quả ---
        final_so_packages = {}
        for so_id, pickings_dict in so_picking_packs.items():
            so = page_sales.filtered(lambda x: x.id == so_id)
            sorted_groups = []
            for p in so.picking_ids:
                if p.id not in pickings_dict:
                    continue
                group = pickings_dict[p.id]
                pack_list = []
                for pname, content in group['packages_dict'].items():
                    content['products_desc'] = ' | '.join([
                        f"{name} (x{int(qty) if qty.is_integer() else qty})"
                        for name, qty in content['product_map'].items()
                        if qty > 0
                    ])
                    pack_list.append(content)

                if pack_list:
                    group['packages'] = sorted(
                        pack_list, key=lambda x: (x.get('sequence') or 0, x['name'])
                    )
                    del group['packages_dict']
                    sorted_groups.append(group)

            final_so_packages[so_id] = sorted_groups

        return final_so_packages
