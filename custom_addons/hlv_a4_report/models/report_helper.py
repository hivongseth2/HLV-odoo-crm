# -*- coding: utf-8 -*-
from odoo import models, api


class HlvReportHelper(models.AbstractModel):
    """Helper methods cho các báo cáo HLV"""
    _name = 'hlv.report.helper'
    _description = 'HLV Report Helper'

    @api.model
    def get_combo_parent_lines_for_picking(self, picking):
        """
        Lấy danh sách các dòng combo parent cần hiển thị trong báo cáo picking.
        
        Logic:
        - Duyệt qua các stock.move trong picking
        - Với mỗi move, kiểm tra xem có sale.order.line nào có x_studio_combo_parent_code 
          trùng với product code của move không
        - Nếu có → lấy dòng combo parent tương ứng
        - Trả về: recordset các dòng SO line cần hiển thị (bao gồm cả parent và child)
        
        Args:
            picking: recordset stock.picking
            
        Returns:
            dict: {
                'lines_to_show': recordset sale.order.line (cả parent lẫn child),
                'parent_map': dict {child_product_code: parent_sol} để mapping
            }
        """
        SaleLine = self.env['sale.order.line']
        if not picking or not picking.move_ids:
            return {'lines_to_show': SaleLine, 'parent_map': {}, 'parent_codes': set(), 'parent_sol_by_code': {}}

        # Xác định Sale Order từ picking
        sale_order = picking.sale_id or (picking.move_ids and picking.move_ids[0].sale_line_id and picking.move_ids[0].sale_line_id.order_id) or False
        if not sale_order:
            return {'lines_to_show': SaleLine, 'parent_map': {}, 'parent_codes': set(), 'parent_sol_by_code': {}}

        # Tập mã sản phẩm có mặt trong picking
        picking_product_codes = {m.product_id.default_code for m in picking.move_ids if m.product_id and m.product_id.default_code}
        if not picking_product_codes:
            return {'lines_to_show': SaleLine, 'parent_map': {}, 'parent_codes': set(), 'parent_sol_by_code': {}}

        parent_codes_to_add = set()
        parent_map = {}  # {child_code: parent_code}

        for sol in sale_order.order_line:
            code = sol.product_id.default_code if sol.product_id else False
            if code and code in picking_product_codes:
                parent_code = getattr(sol, 'x_studio_combo_parent_code', False)
                if parent_code:
                    parent_codes_to_add.add(parent_code)
                    parent_map[code] = parent_code

        # Lấy parent lines trong SO (không phải child)
        parent_lines = SaleLine
        if parent_codes_to_add:
            parent_lines = sale_order.order_line.filtered(
                lambda l: l.product_id
                and l.product_id.default_code in parent_codes_to_add
                and not getattr(l, 'x_studio_is_combo_child', False)
            )

        # Map mã parent → chính xác parent SOL (nếu trùng mã nhiều dòng, ưu tiên sequence nhỏ hơn)
        parent_sol_by_code = {}
        for pl in sorted(parent_lines, key=lambda l: (l.sequence or 0, l.id)):
            pcode = pl.product_id.default_code if pl.product_id else False
            if pcode and pcode not in parent_sol_by_code:
                parent_sol_by_code[pcode] = pl

        # Child lines là các dòng có mã xuất hiện trong picking (cả child lẫn standalone)
        child_lines = sale_order.order_line.filtered(
            lambda l: l.product_id and l.product_id.default_code in picking_product_codes
        )

        lines_to_show = parent_lines | child_lines
        return {
            'lines_to_show': lines_to_show,
            'parent_map': parent_map,
            'parent_codes': parent_codes_to_add,
            'parent_sol_by_code': parent_sol_by_code,
        }

    @api.model
    def get_enriched_lines_for_picking_combo(self, picking):
        """
        Build danh sách hiển thị (parent trước, rồi tới các child của nó; còn lại là standalone).
        Fix: tính qty của parent dựa trên qty của child trong picking.
        """
        result_data = self.get_combo_parent_lines_for_picking(picking)
        lines_to_show = result_data['lines_to_show']
        parent_sol_by_code = result_data.get('parent_sol_by_code', {})  # {parent_code: parent_sol}

        if not lines_to_show:
            return []

        # Tổng qty theo sale_line_id trong picking này
        # Logic: ưu tiên quantity (reserved), fallback qty_done nếu không có
        sol_qty_in_picking = {}
        for move in picking.move_ids:
            if move.sale_line_id:
                # Lấy quantity (reserved qty), nếu không có thì dùng qty_done
                qty_to_add = 0.0
                if hasattr(move, 'quantity') and move.quantity:
                    qty_to_add = move.quantity
                else:
                    # Fallback: tổng qty_done từ move_line_ids
                    qty_to_add = sum(ml.qty_done or 0.0 for ml in move.move_line_ids)
                
                sol_qty_in_picking[move.sale_line_id.id] = sol_qty_in_picking.get(move.sale_line_id.id, 0.0) + qty_to_add

        # Gom nhóm children theo parent_code
        children_by_parent_code = {}  # {parent_code: [child_sol, ...]}
        standalone_lines = []

        for sol in lines_to_show:
            is_child = bool(getattr(sol, 'x_studio_is_combo_child', False))
            code = sol.product_id.default_code if sol.product_id else False
            if is_child:
                pcode = getattr(sol, 'x_studio_combo_parent_code', False)
                if pcode:
                    children_by_parent_code.setdefault(pcode, []).append(sol)
            else:
                standalone_lines.append(sol)

        # Sort
        standalone_lines = sorted(standalone_lines, key=lambda l: (l.sequence or 0, l.id))
        for pcode in children_by_parent_code:
            children_by_parent_code[pcode] = sorted(children_by_parent_code[pcode], key=lambda l: (l.sequence or 0, l.id))

        enriched = []

        for sol in standalone_lines:
            code = sol.product_id.default_code if sol.product_id else ''
            qty_parent_move = sol_qty_in_picking.get(sol.id, 0.0)

            # Là parent nếu có children cùng parent_code = mã này
            is_combo_parent = code in children_by_parent_code

            if is_combo_parent:
                # TÍNH QTY PARENT TỪ CHILD:
                parent_qty_from_children = None
                parent_qty_on_so = sol.product_uom_qty or 0.0  # qty parent trên SOL (để suy tỷ lệ)
                for child_sol in children_by_parent_code[code]:
                    child_qty_in_picking = sol_qty_in_picking.get(child_sol.id, 0.0)
                    if child_qty_in_picking <= 0:
                        continue

                    # Tỷ lệ component = child_qty_trên_SOL / parent_qty_trên_SOL
                    # (nếu trên SO: child_qty = parent_qty * component_qty)
                    comp_ratio = 0.0
                    child_qty_on_so = child_sol.product_uom_qty or 0.0
                    if parent_qty_on_so and parent_qty_on_so > 0:
                        comp_ratio = child_qty_on_so / parent_qty_on_so

                    # Nếu không có tỷ lệ (edge case), fallback: coi comp_ratio = 1 để không crash
                    if comp_ratio and comp_ratio > 0:
                        candidate_parent_qty = child_qty_in_picking / comp_ratio
                    else:
                        candidate_parent_qty = child_qty_in_picking  # fallback

                    parent_qty_from_children = candidate_parent_qty if parent_qty_from_children is None else min(parent_qty_from_children, candidate_parent_qty)

                # Fallback cuối: nếu không child nào có qty>0 thì coi như 0
                parent_qty_from_children = parent_qty_from_children or 0.0

                # Nếu parent có move riêng, dùng max để không bị thấp
                parent_qty_final = max(qty_parent_move, parent_qty_from_children)

                # CHỈ PUSH PARENT NÊU CÓ QTY > 0 (tránh hiển thị combo không có trong picking)
                if parent_qty_final > 0:
                    # Push parent
                    enriched.append({
                        'type': 'parent',
                        'product_name': sol.product_id.display_name if sol.product_id else '',
                        'product_code': code,
                        'qty': parent_qty_final,
                        'uom': sol.product_uom.name if sol.product_uom else '',
                        'price_unit': sol.price_unit or 0.0,
                        'tax_percent': sol.tax_id[0].amount if sol.tax_id else 0.0,
                        'is_combo_child': False,
                        'parent_code': '',
                        'sol': sol,
                    })

                    # Push children (chỉ child có qty>0 trong picking)
                    for child_sol in children_by_parent_code[code]:
                        child_qty = sol_qty_in_picking.get(child_sol.id, 0.0)
                        if child_qty > 0:
                            enriched.append({
                                'type': 'child',
                                'product_name': child_sol.product_id.display_name if child_sol.product_id else '',
                                'product_code': child_sol.product_id.default_code if child_sol.product_id else '',
                                'qty': child_qty,
                                'uom': child_sol.product_uom.name if child_sol.product_uom else '',
                                'price_unit': child_sol.price_unit or 0.0,
                                'tax_percent': child_sol.tax_id[0].amount if child_sol.tax_id else 0.0,
                                'is_combo_child': True,
                                'parent_code': getattr(child_sol, 'x_studio_combo_parent_code', '') or '',
                                'sol': child_sol,
                            })

            else:
                # Standalone (không phải parent combo)
                qty = sol_qty_in_picking.get(sol.id, 0.0)
                if qty > 0:
                    enriched.append({
                        'type': 'standalone',
                        'product_name': sol.product_id.display_name if sol.product_id else '',
                        'product_code': code,
                        'qty': qty,
                        'uom': sol.product_uom.name if sol.product_uom else '',
                        'price_unit': sol.price_unit or 0.0,
                        'tax_percent': sol.tax_id[0].amount if sol.tax_id else 0.0,
                        'is_combo_child': False,
                        'parent_code': '',
                        'sol': sol,
                    })

        return enriched
