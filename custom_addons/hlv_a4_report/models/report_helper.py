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
        Build danh sách hiển thị cho BBBG.
        Hỗ trợ:
        1. BoM Kit (Phantom BoM) - Standard Odoo
        2. Legacy Studio Combo (x_studio_combo_parent_code)
        
        BoM Kit Logic:
        - Parent product: sale_line_id.product_id
        - Components: stock.move.product_id (khác parent)
        - Detect: move.product_id != move.sale_line_id.product_id
        """
        if not picking or not picking.move_ids:
            return []
        
        enriched = []
        processed_sol_ids = set()
        
        # ===== PHASE 1: BoM Kit Logic (Standard Odoo) =====
        # Group moves by sale_line_id
        moves_by_sol = {}
        for move in picking.move_ids:
            if move.sale_line_id:
                if move.sale_line_id not in moves_by_sol:
                    moves_by_sol[move.sale_line_id] = []
                moves_by_sol[move.sale_line_id].append(move)
        
        # Process each SO Line (sorted by sequence)
        sorted_sols = sorted(moves_by_sol.keys(), key=lambda l: (l.sequence or 0, l.id))
        
        for sol in sorted_sols:
            moves = moves_by_sol[sol]
            parent_product = sol.product_id
            
            # Detect BoM Kit: at least one move has different product
            is_bom_kit = any(m.product_id != parent_product for m in moves)
            
            # Skip Legacy Studio Child lines (will process in Phase 2)
            is_studio_child = hasattr(sol, 'x_studio_is_combo_child') and getattr(sol, 'x_studio_is_combo_child', False)
            if is_studio_child:
                continue
            
            # Calculate parent quantity
            if is_bom_kit:
                # For Kit: calculate from component moves in this picking
                # We avoid sol.qty_delivered because it might be 0 before validation
                parent_qty = 0.0
                candidate_qtys = []

                # 1. Try using bom_line_id (Standard Odoo)
                for m in moves:
                    m_qty = m.quantity if hasattr(m, 'quantity') and m.quantity else (m.product_uom_qty or 0.0)
                    if m.bom_line_id and m.bom_line_id.product_qty:
                        candidate_qtys.append(m_qty / m.bom_line_id.product_qty)
                
                # 2. Fallback: Find BoM manually if bom_line_id missing
                if not candidate_qtys:
                    try:
                        boms = self.env['mrp.bom'].sudo()._bom_find(parent_product, company_id=picking.company_id.id or self.env.company.id, bom_type='phantom')
                        bom = boms.get(parent_product)
                        if bom:
                            bom_map = {l.product_id.id: l.product_qty for l in bom.bom_line_ids}
                            for m in moves:
                                m_qty = m.quantity if hasattr(m, 'quantity') and m.quantity else (m.product_uom_qty or 0.0)
                                b_qty = bom_map.get(m.product_id.id, 0.0)
                                if b_qty > 0:
                                    candidate_qtys.append(m_qty / b_qty)
                    except Exception:
                        pass

                if candidate_qtys:
                    parent_qty = max(candidate_qtys)
                else:
                    # Final fallback: use delivered qty (might be 0)
                    parent_qty = sol.qty_delivered or 0.0
            else:
                # For regular product: sum move quantities
                parent_qty = sum(
                    (m.quantity if hasattr(m, 'quantity') and m.quantity else (m.product_uom_qty or 0.0))
                    for m in moves
                )
            
            if parent_qty > 0:
                # Add Parent/Standalone line
                enriched.append({
                    'type': 'parent' if is_bom_kit else 'standalone',
                    'product_name': parent_product.display_name if parent_product else '',
                    'product_code': parent_product.default_code if parent_product else '',
                    'qty': parent_qty,
                    'uom': sol.product_uom.name if sol.product_uom else '',
                    'price_unit': sol.price_unit or 0.0,
                    'tax_percent': sol.tax_id[0].amount if sol.tax_id else 0.0,
                    'is_combo_child': False,
                    'parent_code': '',
                    'sol': sol,
                })
                
                # Add Component lines (if Kit)
                if is_bom_kit:
                    # Group components by product to avoid duplicates
                    comp_qty_map = {}
                    for m in moves:
                        comp_product = m.product_id
                        if comp_product not in comp_qty_map:
                            comp_qty_map[comp_product] = 0.0
                        comp_qty_map[comp_product] += (
                            m.quantity if hasattr(m, 'quantity') and m.quantity else (m.product_uom_qty or 0.0)
                        )
                    
                    # Add each component
                    for comp_product, comp_qty in comp_qty_map.items():
                        if comp_qty > 0:
                            enriched.append({
                                'type': 'child',
                                'product_name': comp_product.display_name,
                                'product_code': comp_product.default_code or '',
                                'qty': comp_qty,
                                'uom': comp_product.uom_id.name if comp_product.uom_id else '',
                                'price_unit': 0.0,
                                'tax_percent': 0.0,
                                'is_combo_child': True,
                                'parent_code': parent_product.default_code or '',
                                'sol': sol,
                            })
                
                processed_sol_ids.add(sol.id)
        
        # ===== PHASE 2: Legacy Studio Combo (Fallback) =====
        result_data = self.get_combo_parent_lines_for_picking(picking)
        lines_to_show = result_data['lines_to_show']
        
        if not lines_to_show:
            return enriched
        
        # Filter out already processed lines
        legacy_lines = lines_to_show.filtered(lambda l: l.id not in processed_sol_ids)
        if not legacy_lines:
            return enriched
        
        # Calculate qty for legacy lines
        sol_qty_in_picking = {}
        for move in picking.move_ids:
            if move.sale_line_id and move.sale_line_id.id not in processed_sol_ids:
                qty_to_add = (
                    move.quantity if (hasattr(move, 'quantity') and move.quantity)
                    else sum(ml.qty_done or 0.0 for ml in move.move_line_ids)
                )
                sol_qty_in_picking[move.sale_line_id.id] = sol_qty_in_picking.get(move.sale_line_id.id, 0.0) + qty_to_add
        
        # Group children by parent_code
        children_by_parent_code = {}
        standalone_lines = []
        
        for sol in legacy_lines:
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
        
        # Process legacy standalone lines
        for sol in standalone_lines:
            code = sol.product_id.default_code if sol.product_id else ''
            qty_parent_move = sol_qty_in_picking.get(sol.id, 0.0)
            is_combo_parent = code in children_by_parent_code
            
            if is_combo_parent:
                # Calculate parent qty from children
                parent_qty_from_children = None
                parent_qty_on_so = sol.product_uom_qty or 0.0
                for child_sol in children_by_parent_code[code]:
                    child_qty_in_picking = sol_qty_in_picking.get(child_sol.id, 0.0)
                    if child_qty_in_picking <= 0:
                        continue
                    
                    comp_ratio = 0.0
                    child_qty_on_so = child_sol.product_uom_qty or 0.0
                    if parent_qty_on_so and parent_qty_on_so > 0:
                        comp_ratio = child_qty_on_so / parent_qty_on_so
                    
                    if comp_ratio and comp_ratio > 0:
                        candidate_parent_qty = child_qty_in_picking / comp_ratio
                    else:
                        candidate_parent_qty = child_qty_in_picking
                    
                    parent_qty_from_children = candidate_parent_qty if parent_qty_from_children is None else min(parent_qty_from_children, candidate_parent_qty)
                
                parent_qty_from_children = parent_qty_from_children or 0.0
                parent_qty_final = max(qty_parent_move, parent_qty_from_children)
                
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
                # Standalone
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

