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
        
        # Build dict để mapping product_code -> move (để lấy qty thực tế từ picking)
        move_by_code = {}
        for move in picking.move_ids:
            if move.product_id and move.product_id.default_code:
                move_by_code[move.product_id.default_code] = move
        
        # Sắp xếp lines: parent trước, child sau
        sorted_lines = sorted(
            lines_to_show,
            key=lambda l: (
                l.x_studio_combo_parent_code or '',  # group by parent
                0 if not l.x_studio_is_combo_child else 1  # parent trước
            )
        )
        
        enriched_lines = []
        for sol in sorted_lines:
            product_code = sol.product_id.default_code if sol.product_id else ''
            
            # Lấy qty từ move (picking) hoặc từ SO line
            qty = 0.0
            move = move_by_code.get(product_code)
            if move:
                qty = move.product_uom_qty or 0.0
            else:
                qty = sol.product_uom_qty or 0.0
            
            # Chỉ hiển thị nếu qty > 0
            if qty <= 0:
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
