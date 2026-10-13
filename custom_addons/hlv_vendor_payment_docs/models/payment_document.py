# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PaymentDocument(models.Model):
    """Chứng từ chi (UNC, phiếu chi, ảnh chuyển khoản…) kế toán tải lên một đề nghị chi của đơn mua — NCC xem được
    trên tab "Tài chính" của link báo giá (trừ khi kế toán ẩn)."""

    _name = "hlv.payment.document"
    _description = "Chứng từ chi NCC"
    _order = "create_date desc, id desc"

    payment_request_id = fields.Many2one("amis.payment.request", string="Đề nghị chi", required=True, index=True,
                                         ondelete="cascade")
    purchase_order_id = fields.Many2one(related="payment_request_id.purchase_order_id", store=True, index=True)
    partner_id = fields.Many2one(related="purchase_order_id.partner_id.commercial_partner_id", string="NCC",
                                 store=True, index=True)
    attachment_id = fields.Many2one("ir.attachment", string="File", required=True, ondelete="cascade")
    name = fields.Char(related="attachment_id.name", string="Tên file")
    mimetype = fields.Char(related="attachment_id.mimetype")
    note = fields.Char(string="Ghi chú", help="VD: UNC đợt 1, phiếu chi tiền mặt…")
    visible_to_vendor = fields.Boolean(string="NCC xem được", default=True)

    @api.model
    def _create_for(self, payment_request, files, note):
        """Tạo chứng từ cho đề nghị chi từ các file đã kiểm (document_error). files: [(tên file, bytes, mimetype)].
        File gắn vào đề nghị chi (res_model) — ai đọc được đề nghị chi thì tải được file."""
        documents = self.browse()
        for filename, data, mimetype in files:
            attachment = self.env["ir.attachment"].create({
                "name": filename,
                "raw": data,
                "mimetype": mimetype or False,
                "res_model": payment_request._name,
                "res_id": payment_request.id,
            })
            documents |= self.create({"payment_request_id": payment_request.id, "attachment_id": attachment.id,
                                      "note": (note or "").strip()[:255] or False})
        return documents

    def unlink(self):
        # Xoá chứng từ là xoá luôn file — không để file mồ côi trên đề nghị chi.
        attachments = self.attachment_id
        result = super().unlink()
        attachments.unlink()
        return result
