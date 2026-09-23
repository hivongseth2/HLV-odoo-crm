# -*- coding: utf-8 -*-
from odoo import models, _
from odoo.exceptions import UserError

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_confirm_safe_check(self):
        # 1. PHẦN KIỂM TRA
        for picking in self:
            seq_code = picking.picking_type_id.sequence_code or ''

            # Phiếu trả hàng vẫn phải xác nhận hàng loạt được, kể cả khi nó
            # mang mã PACK — việc chặn chỉ nhắm vào phiếu đóng gói đi ra.
            # `return_id` ("Return of") là cách nhận diện phiếu trả mà
            # hlv_mobile_barcode đang dùng; đã đối chiếu trên dữ liệu thật:
            # nó cho cùng tập phiếu với move.origin_returned_move_id.
            if 'PACK' in seq_code.upper() and not picking.return_id:
                raise UserError(_(
                    "CẢNH BÁO: Bạn đang chọn Phiếu Đóng Gói (%s).\n"
                    "Hệ thống không cho phép xác nhận phiếu đóng gói từ menu Tác vụ."
                ) % picking.name)

        # 2. PHẦN XỬ LÝ CHÍNH
        # Nếu phiếu đang là "Sẵn sàng", phải dùng button_validate để hoàn thành.
        # Nếu phiếu đang là "Nháp", dùng action_confirm.

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
