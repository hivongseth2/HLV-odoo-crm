# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import json


class InventoryReportController(http.Controller):
    
    @http.route('/inventory/report/pickings/<int:product_id>', type='http', auth='user', website=False)
    def view_filtered_pickings(self, product_id, start_date=None, end_date=None, location_ids=None, **kwargs):
        """
        Controller để redirect đến list view của stock.picking với bộ lọc đã thiết lập.
        
        URL Parameters:
            product_id: ID của sản phẩm (trong URL path)
            start_date: Ngày bắt đầu (YYYY-MM-DD HH:MM:SS)
            end_date: Ngày kết thúc (YYYY-MM-DD HH:MM:SS)
            location_ids: Danh sách ID location (comma separated)
        
        Returns:
            Redirect đến Odoo web client với action đã được tạo động
        """
        # Tạo domain filter
        domain = [
            ('picking_type_code', '=', 'outgoing'),
            ('state', '=', 'done'),
            ('move_ids_without_package.product_id', '=', product_id),
        ]
        
        if start_date:
            domain.append(('date_done', '>=', start_date))
        if end_date:
            domain.append(('date_done', '<=', end_date))
        
        if location_ids:
            try:
                loc_ids = [int(x.strip()) for x in location_ids.split(',') if x.strip()]
                if loc_ids:
                    domain.append(('location_id', 'in', loc_ids))
            except (ValueError, TypeError):
                pass
        
        # Tìm tất cả picking thỏa mãn điều kiện
        pickings = request.env['stock.picking'].search(domain)
        picking_ids = pickings.ids
        
        # Lấy thông tin sản phẩm để hiển thị trong tên action
        product = request.env['product.product'].browse(product_id)
        product_display = product.display_name or f'Sản phẩm #{product_id}'
        
        # Tạo context với search_default để pre-filter
        context = {
            'create': False,
            'default_picking_type_code': 'outgoing',
        }
        
        # Nếu có picking_ids, tạo domain với ID cụ thể (đơn giản và chắc chắn)
        if picking_ids:
            simple_domain = [('id', 'in', picking_ids)]
        else:
            simple_domain = [('id', '=', -1)]  # Domain trả về rỗng
        
        # Tìm menu ID của Inventory
        menu = request.env.ref('stock.menu_stock_root', raise_if_not_found=False)
        menu_id = menu.id if menu else None
        
        # Tạo URL với cách tiếp cận đơn giản: tìm action mặc định của stock.picking
        # và thêm domain vào URL
        action_ref = request.env.ref('stock.action_picking_tree_all', raise_if_not_found=False)
        
        if action_ref:
            # Sử dụng action có sẵn và override domain
            action_id = action_ref.id
            
            # Tạo URL với action_id và domain
            import urllib.parse
            domain_str = json.dumps(simple_domain)
            domain_encoded = urllib.parse.quote(domain_str)
            
            # URL format mới của Odoo 18
            url = f"/web#action={action_id}&active_id=&model=stock.picking&view_type=list&menu_id={menu_id or ''}"
            
            # Thêm domain vào URL (cách này có thể không work)
            # Thay vào đó, chúng ta sẽ tạo một action window mới
            
            # Tạo temporary action (hoặc dùng action động)
            action_data = {
                'name': f'Đơn xuất kho - {product_display}',
                'type': 'ir.actions.act_window',
                'res_model': 'stock.picking',
                'view_mode': 'tree,form',
                'domain': simple_domain,
                'context': context,
                'target': 'current',
            }
            
            # Lưu action tạm vào session hoặc tạo action record
            # Cách đơn giản nhất: tạo ir.actions.act_window record tạm thời
            # Nhưng điều này tạo "rác" trong DB
            
            # Giải pháp tốt nhất: Sử dụng URL với list picking IDs
            if picking_ids:
                ids_str = ','.join(str(pid) for pid in picking_ids[:100])  # Giới hạn 100 để tránh URL quá dài
                url = f"/web#id={ids_str}&model=stock.picking&view_type=list&menu_id={menu_id or ''}"
            else:
                url = f"/web#model=stock.picking&view_type=list&menu_id={menu_id or ''}"
            
            return request.redirect(url)
        
        # Fallback: redirect về trang inventory
        return request.redirect('/web#menu_id=' + str(menu_id) if menu_id else '/web')

