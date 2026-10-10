# -*- coding: utf-8 -*-
"""Wizard "Tạo RFQ" từ dòng YCMH (OCA purchase_request): tự bật "Chỉ gộp nếu trùng Ngày dự kiến" khi có
dòng phần NCC hẹn giao — không thì phần giao ngay và phần hẹn (cùng sản phẩm, cùng NCC) bị gộp thành
MỘT dòng đơn mua, mất ngày hẹn."""

from odoo import api, models


class PurchaseRequestLineMakePurchaseOrder(models.TransientModel):
    _inherit = "purchase.request.line.make.purchase.order"

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if "sync_data_planned" in fields_list and self._hlv_selected_request_lines().filtered("hlv_backorder"):
            res["sync_data_planned"] = True
        return res

    @api.model
    def _hlv_selected_request_lines(self):
        """Dòng YCMH wizard đang mở cho — cùng cách OCA đọc context (active_model / active_ids)."""
        context = self.env.context
        ids = context.get("active_ids") or []
        if context.get("active_model") == "purchase.request.line":
            return self.env["purchase.request.line"].browse(ids)
        if context.get("active_model") == "purchase.request":
            return self.env["purchase.request"].browse(ids).line_ids
        return self.env["purchase.request.line"]
