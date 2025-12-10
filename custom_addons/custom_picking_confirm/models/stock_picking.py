# -*- coding: utf-8 -*-
from odoo import models, _
from odoo.exceptions import UserError

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_confirm_safe_check(self):
        """
        Hàm này kiểm tra phiếu đóng gói trước khi xác nhận.
        """
        for picking in self:
            # Lấy sequence_code, dùng safe navigation để tránh lỗi nếu không có
            seq_code = picking.picking_type_id.sequence_code or ''
            
            # Kiểm tra logic
            if 'PACK' in seq_code.upper():
                raise UserError(_(
                    "CẢNH BÁO: Bạn đang chọn Phiếu Đóng Gói (%s).\n"
                    "Hệ thống không cho phép xác nhận phiếu đóng gói từ menu Tác vụ. "
                    "Vui lòng vào chi tiết phiếu để xử lý."
                ) % picking.name)
        
        # Nếu ổn thỏa, gọi hàm gốc của Odoo
        return self.action_confirm()