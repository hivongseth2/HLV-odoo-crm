# -*- coding: utf-8 -*-
"""Gắn đơn bán từ MISA CRM khi đơn chưa về Odoo.

Ô "Gắn đơn bán" (trang /hoi-gia-ncc) tìm theo nguồn chọn trong Cài đặt. Nguồn MISA CRM: đơn đã đồng bộ về Odoo
(sale.order.misa_id = ID CRM) thì gắn luôn như cũ; chưa về thì phiếu giữ ID + số đơn CRM, và khi đơn về Odoo
(webhook resync — api_resync_by_misa, hoặc nút nhập đơn từ API) thì tự gắn vào phiếu + YCMH của phiếu.
"""
from markupsafe import Markup

from odoo import _, api, fields, models

SALE_ORDER_SOURCE_PARAM = "hlv_vendor_quotation.sale_order_source"
SALE_ORDER_SOURCES = [("odoo", "Đơn bán trong Odoo"), ("crm", "Đơn hàng trên MISA CRM")]
# Đơn api_resync_by_misa vừa tạo mang tên tạm tới khi nạp xong dữ liệu CRM — gắn ở bước sau, khi đã có số đơn thật.
BOOTSTRAP_PREFIX = "TMP-MISA-"


class VendorInquiryCrmOrder(models.Model):
    _inherit = "hlv.vendor.inquiry"

    crm_sale_order_id = fields.Char(string="ID đơn hàng CRM chờ gắn", index=True, copy=False, readonly=True)
    crm_sale_order_code = fields.Char(string="Đơn hàng CRM chờ về Odoo", copy=False, readonly=True, tracking=True)

    @api.model
    def _hlv_sale_order_source(self):
        """Nguồn ô "Gắn đơn bán": "odoo" (mặc định) hoặc "crm"."""
        source = self.env["ir.config_parameter"].sudo().get_param(SALE_ORDER_SOURCE_PARAM)
        return source if source in dict(SALE_ORDER_SOURCES) else "odoo"

    def _hlv_wait_crm_sale_order(self, crm_id, code):
        """Ghi đơn CRM chưa về Odoo lên phiếu để gắn sau (_hlv_link_crm_sale_order). Có số đơn mà YCMH / đơn mua
        của phiếu chưa có mã đơn hàng thì ghi luôn số đơn vào Tài liệu nguồn — thu mua thấy đơn của khách ngay,
        không phải chờ đơn về Odoo."""
        self.ensure_one()
        if (self.crm_sale_order_id, self.crm_sale_order_code) != (crm_id, code):
            self.write({"crm_sale_order_id": crm_id, "crm_sale_order_code": code})
        requests, orders = self._hlv_order_ref_targets()
        if code and (requests or orders) and not any(r.origin for r in requests) and not any(o.origin for o in orders):
            self.action_set_order_ref(code)

    def _hlv_link_crm_sale_order(self, sale_order):
        """Đơn CRM đã về Odoo: gắn vào phiếu + YCMH còn sửa được của phiếu, bỏ dấu chờ."""
        author = self.env.ref("base.partner_root")
        for inquiry in self:
            inquiry._hlv_link_sale_order(sale_order, inquiry._hlv_live_requests(), author)
            inquiry.write({"crm_sale_order_id": False, "crm_sale_order_code": False})
            inquiry.message_post(body=Markup(_("Đơn hàng CRM <b>%s</b> đã về Odoo — tự gắn đơn bán vào phiếu và YCMH.")) % (
                sale_order.name), author_id=author.id)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        # Nút nhập đơn từ API tạo đơn với số + misa_id thật ngay; đơn tạm của webhook gắn sau api_resync_by_misa.
        orders.filtered(lambda o: o.misa_id and not (o.name or "").startswith(BOOTSTRAP_PREFIX))._hlv_link_waiting_inquiries()
        return orders

    def api_resync_by_misa(self, misa_order_id, warehouse_id=None, create_when_missing=True, payload=None):
        result = super().api_resync_by_misa(misa_order_id, warehouse_id=warehouse_id,
                                            create_when_missing=create_when_missing, payload=payload)
        if isinstance(result, dict) and result.get("res_id"):
            self.browse(result["res_id"]).exists()._hlv_link_waiting_inquiries()
        return result

    def _hlv_link_waiting_inquiries(self):
        """Phiếu hỏi giá chưa có đơn bán đang chờ đơn CRM này (theo ID CRM, hoặc số đơn khi đơn nhập tay) → gắn."""
        Inquiry = self.env["hlv.vendor.inquiry"].sudo()
        for order in self.sudo():
            waiting = Inquiry.search([
                ("sale_order_id", "=", False), ("state", "!=", "cancel"),
                "|", ("crm_sale_order_id", "=", order.misa_id or "-"), ("crm_sale_order_code", "=", order.name),
            ])
            if waiting:
                waiting._hlv_link_crm_sale_order(order)
