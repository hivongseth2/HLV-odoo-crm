# -*- coding: utf-8 -*-
from odoo import api, fields, models

from ..services.asset_version import asset_version
from .payment_utils import file_badge, preview_kind

# Model chứa chứng từ → field trỏ tới nó trên hlv.payment.document.
OWNER_FIELDS = {"amis.payment.request": "payment_request_id", "hlv.vendor.debt.payment": "debt_payment_id"}


class PaymentDocument(models.Model):
    """Chứng từ chi (UNC, phiếu chi, ảnh chuyển khoản…) kế toán tải lên một đề nghị chi của đơn mua hoặc một phiếu thanh
    toán công nợ — NCC xem được
    trên tab "Tài chính" của link báo giá (trừ khi kế toán ẩn)."""

    _name = "hlv.payment.document"
    _description = "Chứng từ chi NCC"
    _order = "create_date desc, id desc"

    # Chứng từ thuộc đúng MỘT trong hai: đề nghị chi của một đơn mua, hoặc phiếu thanh toán công nợ nhiều đơn.
    payment_request_id = fields.Many2one("amis.payment.request", string="Đề nghị chi", index=True, ondelete="cascade")
    debt_payment_id = fields.Many2one("hlv.vendor.debt.payment", string="Thanh toán công nợ", index=True,
                                      ondelete="cascade")
    # Chỉ có với chứng từ của đề nghị chi — phiếu công nợ trả nhiều đơn.
    purchase_order_id = fields.Many2one(related="payment_request_id.purchase_order_id", store=True, index=True)
    partner_id = fields.Many2one("res.partner", string="NCC", compute="_compute_partner_id", store=True, index=True)
    attachment_id = fields.Many2one("ir.attachment", string="File", required=True, ondelete="cascade")
    name = fields.Char(related="attachment_id.name", string="Tên file")
    mimetype = fields.Char(related="attachment_id.mimetype")
    note = fields.Char(string="Ghi chú", help="VD: UNC đợt 1, phiếu chi tiền mặt…")
    visible_to_vendor = fields.Boolean(string="NCC xem được", default=True)

    _sql_constraints = [
        ("one_owner", "CHECK((payment_request_id IS NULL) != (debt_payment_id IS NULL))",
         "Chứng từ chi phải gắn vào đúng một đề nghị chi hoặc một phiếu thanh toán công nợ."),
    ]

    @api.depends("purchase_order_id.partner_id.commercial_partner_id", "debt_payment_id.partner_id")
    def _compute_partner_id(self):
        for document in self:
            document.partner_id = (document.purchase_order_id.partner_id.commercial_partner_id
                                   or document.debt_payment_id.partner_id.commercial_partner_id)

    def _hlv_owner(self):
        """Đề nghị chi hoặc phiếu công nợ chứa chứng từ."""
        self.ensure_one()
        return self.payment_request_id or self.debt_payment_id

    def _hlv_preview_kind(self):
        """"image" / "pdf" / "file" — trang hiện ảnh thu nhỏ, xem nhanh trong trang hay chỉ cho tải (preview_kind)."""
        self.ensure_one()
        return preview_kind(self.mimetype, self.name)

    def _hlv_badge(self):
        """Nhãn loại file cho ô chứng từ không có ảnh thu nhỏ (file_badge)."""
        self.ensure_one()
        return file_badge(self.name)

    @api.model
    def _hlv_asset_version(self):
        """?v= cho CSS/JS của module — template gọi được (trang NCC / kế toán không truyền sẵn biến này)."""
        return asset_version()

    @api.model
    def _create_for(self, owner, files, note):
        """Tạo chứng từ cho đề nghị chi hoặc phiếu công nợ (owner) từ các file đã kiểm (document_error).
        files: [(tên file, bytes, mimetype)]. File gắn vào owner (res_model) — ai đọc được owner thì tải được file."""
        owner_field = OWNER_FIELDS[owner._name]
        documents = self.browse()
        for filename, data, mimetype in files:
            attachment = self.env["ir.attachment"].create({
                "name": filename,
                "raw": data,
                "mimetype": mimetype or False,
                "res_model": owner._name,
                "res_id": owner.id,
            })
            documents |= self.create({owner_field: owner.id, "attachment_id": attachment.id,
                                      "note": (note or "").strip()[:255] or False})
        return documents

    def unlink(self):
        # Xoá chứng từ là xoá luôn file — không để file mồ côi trên đề nghị chi.
        attachments = self.attachment_id
        result = super().unlink()
        attachments.unlink()
        return result
