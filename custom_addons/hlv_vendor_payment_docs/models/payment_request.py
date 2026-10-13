# -*- coding: utf-8 -*-
from odoo import api, fields, models

# Đề nghị chi coi là ĐÃ CHI: kế toán duyệt chi trên MISA (approved) hoặc chứng từ MISA thành công (synced) — cùng quy
# tắc amis_callback đang dùng cho "đã thanh toán" của yêu cầu đổi điểm (_compute_misa_payment_is_paid); đổi bên đó
# thì đổi theo ở đây.
PAYMENT_PAID_STATES = ("approved", "synced")

# Đề nghị chi NCC được thấy: đã gửi MISA trở đi. Nháp / lỗi / đang thu hồi / đã thu hồi là việc nội bộ, không hiện.
VENDOR_PAYMENT_STATES = ("pending", "sent", "request_accepted", "approved", "synced")


class AmisPaymentRequest(models.Model):
    _inherit = "amis.payment.request"

    hlv_document_ids = fields.One2many("hlv.payment.document", "payment_request_id", string="Chứng từ chi")
    hlv_document_count = fields.Integer(string="Số chứng từ", compute="_compute_hlv_document_count")

    @api.depends("hlv_document_ids")
    def _compute_hlv_document_count(self):
        for request in self:
            request.hlv_document_count = len(request.hlv_document_ids)

    def _hlv_is_paid(self):
        """Đã chi (kế toán duyệt chi / MISA thành công) — cùng quy tắc amis_callback."""
        self.ensure_one()
        return self.state in PAYMENT_PAID_STATES

    def _hlv_vendor_label(self):
        """Trạng thái NCC đọc: "Đã chi" hoặc "Đang xử lý"."""
        self.ensure_one()
        return "Đã chi" if self._hlv_is_paid() else "Đang xử lý"

    def _hlv_vendor_documents(self):
        """Chứng từ NCC được xem (kế toán không ẩn)."""
        self.ensure_one()
        return self.hlv_document_ids.filtered("visible_to_vendor")
