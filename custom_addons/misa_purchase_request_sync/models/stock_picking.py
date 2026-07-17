# -*- coding: utf-8 -*-
from odoo import models

class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        # Lưu kết quả gốc
        res = super(StockPicking, self)._action_done()
        
        # Sau khi hoàn tất (done), nếu picking thuộc về một Đơn mua hàng (PO)
        for picking in self:
            if picking.purchase_id:
                # Lấy danh sách các Purchase Request liên quan
                prs = picking.purchase_id.order_line.mapped('purchase_request_lines.request_id')
                for pr in prs:
                    if pr.state in ('approved', 'in_progress'):
                        # Kiểm tra xem TẤT CẢ các dòng của PR đã nhận đủ số lượng chưa
                        all_done = True
                        for line in pr.line_ids:
                            if line.product_id.type == 'service':
                                continue # Bỏ qua hàng dịch vụ
                            # Nếu số lượng nhận thực tế (sau khi move done) nhỏ hơn yêu cầu ban đầu -> Chưa hoàn thành
                            if line.product_qty > 0 and line.qty_done < line.product_qty:
                                all_done = False
                                break
                        
                        # Nếu đã hoàn thành toàn bộ, tự động cập nhật trạng thái PR thành done
                        if all_done:
                            pr.sudo().write({'state': 'done'})

        return res
