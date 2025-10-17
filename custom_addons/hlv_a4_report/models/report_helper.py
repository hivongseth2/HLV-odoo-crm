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
        if not picking or not picking.move_ids:
            return {'lines_to_show': self.env['sale.order.line'], 'parent_map': {}}
        
        # Lấy sale order từ picking
        sale_order = False
        if picking.sale_id:
            sale_order = picking.sale_id
        elif picking.move_ids and picking.move_ids[0].sale_line_id:
            sale_order = picking.move_ids[0].sale_line_id.order_id
        
        if not sale_order:
            return {'lines_to_show': self.env['sale.order.line'], 'parent_map': {}}
        
        # Lấy tất cả product codes trong picking
        picking_product_codes = set()
        for move in picking.move_ids:
            if move.product_id and move.product_id.default_code:
                picking_product_codes.add(move.product_id.default_code)
        
        if not picking_product_codes:
            return {'lines_to_show': self.env['sale.order.line'], 'parent_map': {}}
        
        # Tìm các dòng combo parent liên quan
        parent_codes_to_add = set()
        parent_map = {}  # {child_code: parent_sol}
        
        for sol in sale_order.order_line:
            product_code = sol.product_id.default_code if sol.product_id else False
            
            # Kiểm tra nếu sản phẩm này có trong picking
            if product_code and product_code in picking_product_codes:
                # Kiểm tra xem có phải combo child không
                parent_code = sol.x_studio_combo_parent_code
                if parent_code:
                    # Đây là combo child → cần tìm parent
                    parent_codes_to_add.add(parent_code)
                    parent_map[product_code] = parent_code
        
        # Tìm các dòng parent trong SO
        parent_lines = self.env['sale.order.line']
        if parent_codes_to_add:
            parent_lines = sale_order.order_line.filtered(
                lambda l: l.product_id and 
                         l.product_id.default_code in parent_codes_to_add and
                         not l.x_studio_is_combo_child
            )
        
        # Tìm các dòng child tương ứng với picking
        child_lines = sale_order.order_line.filtered(
            lambda l: l.product_id and 
                     l.product_id.default_code in picking_product_codes
        )
        
        # Kết hợp parent + child
        lines_to_show = parent_lines | child_lines
        
        return {
            'lines_to_show': lines_to_show,
            'parent_map': parent_map,
            'parent_codes': parent_codes_to_add
        }
    
    @api.model
    def get_enriched_lines_for_picking_combo(self, picking):
        """
        Trả về danh sách các dòng hiển thị kết hợp giữa stock.move và sale.order.line
        cho báo cáo combo, bao gồm cả dòng parent.
        
        Logic cải tiến:
        - Duyệt qua từng sale.order.line riêng biệt
        - Với mỗi SOL, chỉ lấy qty_delivered (số lượng đã giao trong picking này)
        - Điều này tránh tình huống sản phẩm B vừa là combo child vừa mua lẻ
        
        Returns:
            list of dict: [
                {
                    'type': 'parent' hoặc 'child',
                    'product_name': tên sản phẩm,
                    'product_code': mã sản phẩm,
                    'qty': số lượng,
                    'uom': đơn vị,
                    'price_unit': đơn giá (nếu có),
                    'tax_percent': % thuế (nếu có),
                    'is_combo_child': True/False,
                    'parent_code': mã parent (nếu là child),
                    'sol': sale.order.line object (nếu có)
                }
            ]
        """
        result_data = self.get_combo_parent_lines_for_picking(picking)
        lines_to_show = result_data['lines_to_show']
        parent_map = result_data['parent_map']
        
        if not lines_to_show:
            return []
        
        # Build mapping: (product_code, sale_line_id) -> qty trong picking này
        # Dựa trên stock.move.line (chi tiết move) thay vì stock.move
        sol_qty_in_picking = {}  # {sol.id: qty_delivered}
        
        for move in picking.move_ids:
            if move.sale_line_id:
                sol_id = move.sale_line_id.id
                if sol_id not in sol_qty_in_picking:
                    sol_qty_in_picking[sol_id] = 0.0
                # Cộng dồn qty từ move này
                sol_qty_in_picking[sol_id] += move.product_uom_qty or 0.0
        
        # Build mapping parent_code -> parent SOL để lấy sequence
        parent_sol_map = {}  # {parent_code: parent_sol}
        for sol in lines_to_show:
            if not sol.x_studio_is_combo_child and sol.product_id and sol.product_id.default_code:
                parent_sol_map[sol.product_id.default_code] = sol
        
        # Sắp xếp lines: 
        # 1. Ưu tiên parent trước
        # 2. Child sắp xếp ngay sau parent của nó
        # 3. Sản phẩm lẻ (không phải combo) xếp cuối
        def get_sort_key(sol):
            # Nếu là parent combo → xếp theo sequence của nó
            if not sol.x_studio_is_combo_child:
                return (sol.sequence or 0, 0, sol.id)
            
            # Nếu là child → xếp ngay sau parent của nó
            parent_code = sol.x_studio_combo_parent_code
            if parent_code and parent_code in parent_sol_map:
                parent_sol = parent_sol_map[parent_code]
                # Xếp ngay sau parent: dùng sequence của parent, type=1 (child), sequence của child
                return (parent_sol.sequence or 0, 1, sol.sequence or 0, sol.id)
            
            # Trường hợp đặc biệt: child nhưng không tìm thấy parent
            return (sol.sequence or 0, 1, sol.sequence or 0, sol.id)
        
        sorted_lines = sorted(lines_to_show, key=get_sort_key)
        
        enriched_lines = []
        for sol in sorted_lines:
            product_code = sol.product_id.default_code if sol.product_id else ''
            
            # Lấy qty từ mapping (số lượng thực tế giao trong picking này)
            # Nếu không có trong picking → kiểm tra xem có phải là parent không
            qty = sol_qty_in_picking.get(sol.id, 0.0)
            
            # Với parent line: không có move trực tiếp, nhưng vẫn cần hiển thị
            # → lấy qty = 0 hoặc qty từ SO line để hiển thị thông tin
            if not sol.x_studio_is_combo_child and qty == 0:
                # Đây là parent, kiểm tra xem có child nào được giao không
                has_delivered_child = False
                parent_code = sol.product_id.default_code
                for other_sol in lines_to_show:
                    if (other_sol.x_studio_is_combo_child and 
                        other_sol.x_studio_combo_parent_code == parent_code and
                        sol_qty_in_picking.get(other_sol.id, 0.0) > 0):
                        has_delivered_child = True
                        break
                
                # Nếu có child được giao → hiển thị parent với qty = 0
                if not has_delivered_child:
                    continue
            
            # Bỏ qua nếu qty <= 0 (trừ parent có child)
            if qty <= 0 and sol.x_studio_is_combo_child:
                continue
            
            enriched_lines.append({
                'type': 'child' if sol.x_studio_is_combo_child else 'parent',
                'product_name': sol.product_id.display_name if sol.product_id else '',
                'product_code': product_code,
                'qty': qty,
                'uom': sol.product_uom.name if sol.product_uom else '',
                'price_unit': sol.price_unit or 0.0,
                'tax_percent': sol.tax_id[0].amount if sol.tax_id else 0.0,
                'is_combo_child': sol.x_studio_is_combo_child or False,
                'parent_code': sol.x_studio_combo_parent_code or '',
                'sol': sol,
            })
        
        return enriched_lines
