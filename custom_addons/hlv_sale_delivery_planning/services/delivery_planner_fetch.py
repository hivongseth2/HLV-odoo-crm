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

        # --- Attachments trực tiếp (search_read thay vì browse) ---
        for att in self.env['ir.attachment'].sudo().search_read([
            ('res_model', '=', 'stock.picking'),
            ('res_id', 'in', all_picking_ids),
        ], ['id', 'name', 'res_id', 'mimetype']):
            if att['name'] and (
                att['name'].lower().endswith(('.webm', '.mp4'))
                or 'video' in (att.get('mimetype') or '')
            ):
                att_by_picking.setdefault(att['res_id'], []).append({
                    'id': att['id'], 'name': att['name'],
                    'url': f"/web/content/{att['id']}?download=true",
                })

        # --- Video trong chatter: 1 query message + 1 query attachment ---
        # Optimization: only fetch messages that actually contain a video URL or have attachments.
        # Cuts payload from ALL chatter messages (with full HTML body) down to relevant ones.
        msg_recs = self.env['mail.message'].sudo().search_read([
            ('model', '=', 'stock.picking'),
            ('res_id', 'in', all_picking_ids),
            '|',
                ('attachment_ids', '!=', False),
                ('body', 'ilike', '.webm'),
        ], ['id', 'res_id', 'attachment_ids', 'body'])

        # Batch load attachments của tất cả messages 1 lần
        all_msg_att_ids = [att_id for m in msg_recs for att_id in (m.get('attachment_ids') or [])]
        msg_att_map = {}
        if all_msg_att_ids:
            for att in self.env['ir.attachment'].sudo().search_read(
                [('id', 'in', all_msg_att_ids)],
                ['id', 'name', 'mimetype'],
            ):
                msg_att_map[att['id']] = att

        for msg in msg_recs:
            pick_id = msg['res_id']
            for att_id in (msg.get('attachment_ids') or []):
                att = msg_att_map.get(att_id)
                if not att:
                    continue
                if att.get('name') and (
                    att['name'].lower().endswith(('.webm', '.mp4'))
                    or 'video' in (att.get('mimetype') or '')
                ):
                    url = f"/web/content/{att['id']}?download=true"
                    if not any(a['url'] == url for a in att_by_picking.get(pick_id, [])):
                        att_by_picking.setdefault(pick_id, []).append(
                            {'id': att['id'], 'name': att['name'], 'url': url}
                        )

            body = msg.get('body') or ''
            # Only the second regex actually works — the first regex `r'href=[\'"]([\'"]+)[\'"]'`
            # required the URL to consist solely of quote chars (always 0 matches), so removed.
            if body and '.webm' in body:
                urls = re.findall(r'(\/web\/content\/[0-9]+.*?\.webm)', body)
                for i, url in enumerate(urls):
                    clean_url = url.replace('&amp;', '&')
                    if not any(u['url'] == clean_url for u in att_by_picking.get(pick_id, [])):
                        att_by_picking.setdefault(pick_id, []).append({
                            'id': f"log_{msg['id']}_{i}",
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
        của các SO, nhóm theo SO -> Picking -> Package.
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

        # --- Metadata kiện: search_read thay vì browse ---
        package_ids = list(set(
            ml['result_package_id'][0] for ml in move_lines if ml['result_package_id']
        ))
        pack_dict = {}
        if package_ids:
            pack_raw = self.env['stock.quant.package'].sudo().search_read(
                [('id', 'in', package_ids)],
                ['id', 'name', 'location_id', 'pack_sequence', 'pack_total'],
            )
            # Batch fetch location usage để detect kiện đã giao (location ngoài kho)
            pack_loc_ids = list({r['location_id'][0] for r in pack_raw if r.get('location_id')})
            loc_usage_map = {}
            if pack_loc_ids:
                for lr in self.env['stock.location'].sudo().search_read(
                    [('id', 'in', pack_loc_ids)], ['id', 'usage']
                ):
                    loc_usage_map[lr['id']] = lr['usage']
            for p in pack_raw:
                # location_id là Many2one → [id, name] hoặc False
                loc_raw = p.get('location_id')
                loc_id = loc_raw[0] if isinstance(loc_raw, (list, tuple)) and loc_raw else None
                loc_name = loc_raw[1] if isinstance(loc_raw, (list, tuple)) and loc_raw else ''
                loc_usage = loc_usage_map.get(loc_id, 'internal')
                # is_shipped = True nếu kiện đã rời kho (customer/supplier location)
                # → items đã tính vào qty_delivered, không double-count trong qty_packed
                is_shipped = loc_usage not in ('internal', 'transit', 'view')
                pack_dict[p['id']] = {
                    'id': p['id'],
                    'name': p.get('name') or '',
                    'location_name': loc_name,
                    'is_shipped': is_shipped,
                    'pack_sequence': p.get('pack_sequence') or 0,
                    'pack_total': p.get('pack_total') or 0,
                }

        # --- Thông tin picking: search_read thay vì browse ---
        pickings_info_map = {}
        for r in self.env['stock.picking'].sudo().search_read(
            [('id', 'in', all_picking_ids)],
            ['id', 'state', 'picking_type_id'],
        ):
            pt_raw = r.get('picking_type_id')
            pickings_info_map[r['id']] = {
                'state': r['state'],
                'code': '',  # điền sau
                '_pt_id': pt_raw[0] if isinstance(pt_raw, (list, tuple)) else None,
            }
        # Lấy code từ picking_type
        pt_ids_needed = list({v['_pt_id'] for v in pickings_info_map.values() if v['_pt_id']})
        if pt_ids_needed:
            pt_code_map = {r['id']: r.get('code', '') for r in self.env['stock.picking.type'].sudo().search_read(
                [('id', 'in', pt_ids_needed)], ['id', 'code'],
            )}
            for info in pickings_info_map.values():
                info['code'] = pt_code_map.get(info['_pt_id'], 'outgoing')
        picking_info_map = pickings_info_map

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
                    'location_name': '', 'is_shipped': False, 'pack_sequence': 0, 'pack_total': 0,
                })
                so_picking_packs[so_id][pick_id]['packages_dict'][pname] = {
                    'id': pid,
                    'name': pname,
                    'picking_id': pick_id,
                    'location_name': pack_info.get('location_name') or '',
                    'is_shipped': pack_info.get('is_shipped', False),
                    'sequence': pack_info.get('pack_sequence') or 0,
                    'total': pack_info.get('pack_total') or 0,
                    'product_map': {},
                    'product_id_map': {},
                }

            p_content = so_picking_packs[so_id][pick_id]['packages_dict'][pname]
            prod_id = ml['product_id'][0] if ml['product_id'] else False
            prod_name = ml['product_id'][1] if ml['product_id'] else 'Unknown'
            qty = float(ml['quantity']) if ml.get('quantity') else 0.0
            p_content['product_map'][prod_name] = (
                p_content['product_map'].get(prod_name, 0.0) + qty
            )
            if prod_id:
                p_content['product_id_map'][prod_id] = (
                    p_content['product_id_map'].get(prod_id, 0.0) + qty
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
