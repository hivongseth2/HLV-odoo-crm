# -*- coding: utf-8 -*-
"""Khoá giá dòng đơn mua lên từ trang hỏi giá: thu mua không sửa đơn giá / chiết khấu / thuế ở backend nữa.

Giá trên dòng là giá NCC báo trên trang hỏi giá, sale chọn, thu mua duyệt YCMH. Muốn giá khác thì thu mua "Đề
xuất giá" (po_price_proposal.py) → sale hỏi lại NCC trên trang NCC → sale gửi thu mua duyệt → duyệt mới đổi giá, ghi
thành một phiên bản của đơn (hlv.po.revision) — cột "Lịch sử" trên từng dòng xem lại cũ → mới.

Chỉ dòng có YCMH gắn với phiếu hỏi giá (purchase_request_line_price — nơi định nghĩa "gắn với hỏi giá"): đơn mua không
gắn với hỏi giá (tạo tay, lên từ MISA) không có phiếu để sale hỏi lại, thu mua vẫn nhập giá như cũ.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_round

# Đường được phép ghi giá dòng đã khoá: wizard Tạo RFQ (giá đã chọn trên YCMH), áp phiên bản đã duyệt
# (purchase_order_revision — NCC yêu cầu / thu mua duyệt giá sale hỏi lại).
PRICE_WRITE_CTX = "hlv_po_price_write"
LOCKED_PRICE_FIELDS = ("price_unit", "discount", "taxes_id")
# Ghi một trong các ô này làm Odoo tính lại đơn giá + chiết khấu theo bảng giá NCC
# (_compute_price_unit_and_date_planned_and_name) — dòng đã khoá thì ghi kèm giá đang có để Odoo không tính đè.
REPRICE_TRIGGERS = ("product_qty", "product_uom", "product_id")


class PurchaseOrderLinePriceLock(models.Model):
    _inherit = "purchase.order.line"

    hlv_price_locked = fields.Boolean(
        string="Giá theo hỏi giá", compute="_compute_hlv_price_locked",
        help="Dòng lên từ YCMH gắn với phiếu hỏi giá: đơn giá không sửa tay được — bấm \"Đề xuất giá\" để sale hỏi "
             "lại NCC, giá mới về thì thu mua duyệt.",
    )
    hlv_revision_line_ids = fields.One2many("hlv.po.revision.line", "order_line_id", string="Thay đổi của dòng")
    hlv_change_count = fields.Integer(string="Số lần đổi", compute="_compute_hlv_change_count")

    @api.depends("purchase_request_lines.hlv_price_locked")
    def _compute_hlv_price_locked(self):
        for line in self:
            line.hlv_price_locked = any(line.sudo().purchase_request_lines.mapped("hlv_price_locked"))

    @api.depends("hlv_revision_line_ids.revision_id.state")
    def _compute_hlv_change_count(self):
        for line in self:
            line.hlv_change_count = len(line.hlv_revision_line_ids._hlv_applied())

    def _hlv_price_key(self):
        """Những gì quyết định giá sau VAT của dòng — so trước / sau khi ghi."""
        self.ensure_one()
        digits = self.env["decimal.precision"].precision_get("Product Price")
        return (float_round(self.price_unit, precision_digits=digits), float_round(self.discount, precision_digits=2),
                tuple(sorted(self.taxes_id.ids)))

    def write(self, vals):
        touched = any(key in vals for key in LOCKED_PRICE_FIELDS + REPRICE_TRIGGERS)
        if not touched or self.env.context.get(PRICE_WRITE_CTX):
            return super().write(vals)
        locked = self.filtered("hlv_price_locked")
        if not locked:
            return super().write(vals)
        before = {line.id: line._hlv_price_key() for line in locked}
        if any(key in vals for key in REPRICE_TRIGGERS):
            # Giá ghi kèm SL là giá Odoo tính lại theo bảng giá NCC (VD bổ sung hàng gộp vào RFQ nháp — purchase_stock)
            # chứ không phải giá ai chọn: giữ giá đang có, không báo lỗi làm hỏng luồng đó.
            for line in locked:
                kept = {"price_unit": line.price_unit, "discount": line.discount}
                super(PurchaseOrderLinePriceLock, line).write(dict(vals, **kept))
            others = self - locked
            result = super(PurchaseOrderLinePriceLock, others).write(vals) if others else True
        else:
            result = super().write(vals)
        changed = locked.filtered(lambda l: l._hlv_price_key() != before[l.id])
        if changed:
            raise UserError(_(
                "%s lên từ trang hỏi giá — không sửa đơn giá / chiết khấu / thuế trực tiếp. Bấm \"Đề xuất giá\" trên "
                "dòng: sale hỏi lại NCC rồi gửi giá mới để thu mua duyệt.",
                ", ".join(changed.mapped(lambda l: l.product_id.display_name or l.name)),
            ))
        return result

    def action_hlv_propose_price(self):
        """Thu mua mở hộp đề xuất giá gợi ý cho dòng này."""
        self.ensure_one()
        self.env["hlv.po.price.proposal"]._check_can_propose(self)
        return {
            "type": "ir.actions.act_window",
            "name": _("Đề xuất giá — %s", self.product_id.display_name),
            "res_model": "hlv.po.price.proposal.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_order_line_id": self.id},
        }

    def action_hlv_view_changes(self):
        """Lịch sử thay đổi của dòng (mọi phiên bản đã áp vào đơn) — như cột "Lịch sử" trên dòng đơn bán."""
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("hlv_vendor_quotation.action_po_line_changes")
        action["domain"] = [("id", "in", self.hlv_revision_line_ids._hlv_applied().ids)]
        action["name"] = _("Lịch sử thay đổi — %s", self.product_id.display_name)
        return action
