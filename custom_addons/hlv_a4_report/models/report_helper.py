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
        - Xây dựng cấu trúc cây: parent -> [children]
        - Duyệt theo thứ tự: parent, rồi children của nó, rồi parent khác...
        
        Returns:
            list of dict
        """
        result_data = self.get_combo_parent_lines_for_picking(picking)
        lines_to_show = result_data['lines_to_show']
        parent_map = result_data['parent_map']
        
        if not lines_to_show:
            return []
        
        # Build mapping: sol.id -> qty trong picking này
        sol_qty_in_picking = {}
        for move in picking.move_ids:
            if move.sale_line_id:
                sol_id = move.sale_line_id.id
                if sol_id not in sol_qty_in_picking:
                    sol_qty_in_picking[sol_id] = 0.0
                sol_qty_in_picking[sol_id] += move.product_uom_qty or 0.0
        
        # Xây dựng cấu trúc cây: parent_code -> [child_sols]
        children_by_parent = {}  # {parent_code: [child_sol1, child_sol2, ...]}
        standalone_lines = []  # Các dòng không phải combo (parent hoặc lẻ)
        
        for sol in lines_to_show:
            if sol.x_studio_is_combo_child:
                # Đây là combo child
                parent_code = sol.x_studio_combo_parent_code
                if parent_code:
                    if parent_code not in children_by_parent:
                        children_by_parent[parent_code] = []
                    children_by_parent[parent_code].append(sol)
            else:
                # Đây là parent hoặc sản phẩm lẻ
                standalone_lines.append(sol)
        
        # Sắp xếp standalone lines theo sequence
        standalone_lines = sorted(standalone_lines, key=lambda l: (l.sequence or 0, l.id))
        
        # Sắp xếp children trong mỗi nhóm theo sequence
        for parent_code in children_by_parent:
            children_by_parent[parent_code] = sorted(
                children_by_parent[parent_code], 
                key=lambda l: (l.sequence or 0, l.id)
            )
        
        # Xây dựng danh sách kết quả
        enriched_lines = []
        
        for sol in standalone_lines:
            product_code = sol.product_id.default_code if sol.product_id else ''
            qty = sol_qty_in_picking.get(sol.id, 0.0)
            
            # Kiểm tra xem đây có phải parent của combo không
            is_combo_parent = product_code in children_by_parent
            
            # Nếu là parent nhưng không có qty → vẫn hiển thị nếu có children
            if is_combo_parent:
                # Thêm parent line (có thể qty=0)
                enriched_lines.append({
                    'type': 'parent',
                    'product_name': sol.product_id.display_name if sol.product_id else '',
                    'product_code': product_code,
                    'qty': qty,
                    'uom': sol.product_uom.name if sol.product_uom else '',
                    'price_unit': sol.price_unit or 0.0,
                    'tax_percent': sol.tax_id[0].amount if sol.tax_id else 0.0,
                    'is_combo_child': False,
                    'parent_code': '',
                    'sol': sol,
                })
                
                # Thêm các children ngay sau parent
                for child_sol in children_by_parent[product_code]:
                    child_qty = sol_qty_in_picking.get(child_sol.id, 0.0)
                    if child_qty > 0:  # Chỉ hiển thị child có qty > 0
                        enriched_lines.append({
                            'type': 'child',
                            'product_name': child_sol.product_id.display_name if child_sol.product_id else '',
                            'product_code': child_sol.product_id.default_code if child_sol.product_id else '',
                            'qty': child_qty,
                            'uom': child_sol.product_uom.name if child_sol.product_uom else '',
                            'price_unit': child_sol.price_unit or 0.0,
                            'tax_percent': child_sol.tax_id[0].amount if child_sol.tax_id else 0.0,
                            'is_combo_child': True,
                            'parent_code': child_sol.x_studio_combo_parent_code or '',
                            'sol': child_sol,
                        })
            else:
                # Đây là sản phẩm lẻ (không phải parent)
                if qty > 0:
                    enriched_lines.append({
                        'type': 'standalone',
                        'product_name': sol.product_id.display_name if sol.product_id else '',
                        'product_code': product_code,
                        'qty': qty,
                        'uom': sol.product_uom.name if sol.product_uom else '',
                        'price_unit': sol.price_unit or 0.0,
                        'tax_percent': sol.tax_id[0].amount if sol.tax_id else 0.0,
                        'is_combo_child': False,
                        'parent_code': '',
                        'sol': sol,
                    })
        
        return enriched_lines
