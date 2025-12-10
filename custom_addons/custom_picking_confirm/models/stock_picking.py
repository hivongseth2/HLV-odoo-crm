# -*- coding: utf-8 -*-
from odoo import models, _
from odoo.exceptions import UserError

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_confirm_safe_check(self):
        # 1. PHẦN KIỂM TRA (GIỮ NGUYÊN)
        for picking in self:
            seq_code = picking.picking_type_id.sequence_code or ''
            
            if 'PACK' in seq_code.upper():
                raise UserError(_(
                    "CẢNH BÁO: Bạn đang chọn Phiếu Đóng Gói (%s).\n"
                    "Hệ thống không cho phép xác nhận phiếu đóng gói từ menu Tác vụ."
                ) % picking.name)
        
        # 2. PHẦN XỬ LÝ CHÍNH (SỬA LẠI CHỖ NÀY)
        # Nếu phiếu đang là "Sẵn sàng", phải dùng button_validate để hoàn thành.
        # Nếu phiếu đang là "Nháp", dùng action_confirm.
        
        # Để an toàn cho cả 2 trường hợp, ta lọc ra:
        
        # Nhóm 1: Các phiếu đang Nháp -> Chuyển sang Sẵn sàng
        draft_pickings = self.filtered(lambda p: p.state == 'draft')
        if draft_pickings:
            draft_pickings.action_confirm()

        # Nhóm 2: Các phiếu Sẵn sàng -> Validate (Hoàn thành)
        # Lưu ý: Hàm này chỉ chạy tốt nếu bạn đã điền số lượng "Hoàn tất" (Done qty) 
        # hoặc cấu hình cho phép Dịch chuyển ngay lập tức.
        ready_pickings = self.filtered(lambda p: p.state not in ['draft', 'cancel', 'done'])
        if ready_pickings:
            ready_pickings.button_validate()

        # 3. RELOAD GIAO DIỆN
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }