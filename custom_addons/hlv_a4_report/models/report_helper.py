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

        # Map mã parent → chính xác parent SOL
        parent_sol_by_code = {}
        for pl in sorted(parent_lines, key=lambda l: (l.sequence or 0, l.id)):
            pcode = pl.product_id.default_code if pl.product_id else False
            if pcode and pcode not in parent_sol_by_code:
                parent_sol_by_code[pcode] = pl

        # Child lines là các dòng có mã xuất hiện trong picking
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
        Build danh sách hiển thị với số lượng thực tế đã giao trong picking này.
        
        LOGIC TÍNH SỐ LƯỢNG COMBO CHA:
        - Dựa vào số lượng thực tế đã giao của các sản phẩm con trong picking
        - Tìm số lượng combo tối thiểu có thể tạo thành từ các con
        - Ví dụ: Combo gồm 2A + 3B, nếu giao 4A + 6B → tạo được 2 combo
        """
        result_data = self.get_combo_parent_lines_for_picking(picking)
        lines_to_show = result_data['lines_to_show']
        parent_sol_by_code = result_data.get('parent_sol_by_code', {})

        if not lines_to_show:
            return []

        # Tính tổng qty ĐÃ GIAO (done_qty) theo sale_line_id trong picking này
        sol_qty_done = {}
        for move in picking.move_ids:
            if move.sale_line_id:
                # Quantity_done là số lượng thực tế đã giao
                qty = move.quantity_done if move.state == 'done' else move.product_uom_qty
                sol_qty_done[move.sale_line_id.id] = sol_qty_done.get(move.sale_line_id.id, 0.0) + (qty or 0.0)

        # Lấy thông tin combo từ SO để tính tỷ lệ
        sale_order = picking.sale_id or (picking.move_ids and picking.move_ids[0].sale_line_id and picking.move_ids[0].sale_line_id.order_id)
        
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
            qty_parent_done = sol_qty_done.get(sol.id, 0.0)

            # Là parent nếu có children cùng parent_code = mã này
            is_combo_parent = code in children_by_parent_code

            if is_combo_parent:
                # TÍNH SỐ LƯỢNG COMBO CHA TỪ SỐ LƯỢNG CON ĐÃ GIAO
                parent_qty_calculated = None
                parent_qty_on_so = sol.product_uom_qty or 1.0  # Để tránh chia cho 0
                
                for child_sol in children_by_parent_code[code]:
                    child_qty_done = sol_qty_done.get(child_sol.id, 0.0)
                    
                    # Tỷ lệ component trong SO (ví dụ: 1 combo = 2A, thì ratio = 2)
                    child_qty_on_so = child_sol.product_uom_qty or 0.0
                    component_ratio = child_qty_on_so / parent_qty_on_so if parent_qty_on_so > 0 else 1.0
                    
                    if component_ratio > 0:
                        # Số combo có thể tạo = số lượng con đã giao / tỷ lệ component
                        possible_combo_qty = child_qty_done / component_ratio
                        
                        # Lấy MIN để đảm bảo đủ tất cả component
                        if parent_qty_calculated is None:
                            parent_qty_calculated = possible_combo_qty
                        else:
                            parent_qty_calculated = min(parent_qty_calculated, possible_combo_qty)

                # Nếu parent có move riêng (edge case), lấy max
                parent_qty_final = parent_qty_calculated or 0.0
                if qty_parent_done > 0:
                    parent_qty_final = max(parent_qty_final, qty_parent_done)

                # CHỈ HIỂN THỊ NẾU CÓ SỐ LƯỢNG > 0
                if parent_qty_final > 0:
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

                    # Push children (chỉ child có qty>0)
                    for child_sol in children_by_parent_code[code]:
                        child_qty = sol_qty_done.get(child_sol.id, 0.0)
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
                qty = sol_qty_done.get(sol.id, 0.0)
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