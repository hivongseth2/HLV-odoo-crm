# -*- coding: utf-8 -*-
"""Gắn đơn bán từ MISA CRM khi đơn chưa về Odoo.

Ô "Mã đơn hàng của khách" (trang /hoi-gia-ncc) gợi ý theo nguồn chọn trong Cài đặt. Nguồn MISA CRM: đơn đã đồng bộ về Odoo
(sale.order.misa_id = ID CRM) thì gắn luôn như cũ; chưa về thì phiếu giữ ID + số đơn CRM, và khi đơn về Odoo
(webhook resync — api_resync_by_misa, hoặc nút nhập đơn từ API) thì tự gắn vào phiếu + YCMH của phiếu.
"""
from markupsafe import Markup

from odoo import _, api, fields, models

from .vendor_quote_utils import normalize_origin

SALE_ORDER_SOURCE_PARAM = "hlv_vendor_quotation.sale_order_source"
SALE_ORDER_SOURCES = [("odoo", "Đơn bán trong Odoo"), ("crm", "Đơn hàng trên MISA CRM")]
# Đơn api_resync_by_misa vừa tạo mang tên tạm tới khi nạp xong dữ liệu CRM — gắn ở bước sau, khi đã có số đơn thật.
BOOTSTRAP_PREFIX = "TMP-MISA-"


def _single_pick(origin, crm_picks):
    """(ID CRM, số đơn) khi đúng một đơn CRM đã chọn còn nằm trong origin (đã normalize_origin); không thì None."""
    codes = set((origin or "").split(", "))
    picks = [pick for pick in crm_picks or () if pick[1] in codes]
    return picks[0] if len(picks) == 1 else None


class VendorInquiryCrmOrder(models.Model):
    _inherit = "hlv.vendor.inquiry"

    crm_sale_order_id = fields.Char(string="ID đơn hàng CRM chờ gắn", index=True, copy=False, readonly=True)
    crm_sale_order_code = fields.Char(string="Đơn hàng CRM chờ về Odoo", copy=False, readonly=True, tracking=True)

    @api.model
    def _hlv_sale_order_source(self):
        """Nguồn gợi ý của ô mã đơn hàng: "odoo" (mặc định) hoặc "crm"."""
        source = self.env["ir.config_parameter"].sudo().get_param(SALE_ORDER_SOURCE_PARAM)
        return source if source in dict(SALE_ORDER_SOURCES) else "odoo"

    def _hlv_order_from_ref(self, origin, crm_picks):
        """Đơn bán Odoo ứng với mã đơn hàng sale nhập: số đơn trùng một mã trong origin, không thì đơn CRM sale chọn
        mà đã đồng bộ về (misa_id — có thể vừa về giữa lúc tìm và lúc bấm). Không có → rỗng."""
        origin = normalize_origin(origin)
        order = self._hlv_sale_order_from_origin(origin)
        pick = _single_pick(origin, crm_picks)
        if not order and pick:
            order = self.env["sale.order"].sudo().search([("misa_id", "=", pick[0])], limit=1)
        return order

    def action_set_order_ref_crm(self, origin, crm_picks=()):
        """action_set_order_ref + đơn MISA CRM chưa về Odoo. crm_picks: [(ID CRM, số đơn)] sale chọn ở ô mã đơn hàng
        (nguồn gợi ý = MISA CRM). Đúng một đơn còn trong origin và phiếu chưa có đơn bán → gắn ngay nếu đơn đã
        về, chưa về thì phiếu giữ lại (_hlv_link_crm_sale_order khi đồng bộ). Mã đang chờ bị xoá khỏi ô → bỏ chờ."""
        self.ensure_one()
        orders = self.action_set_order_ref(origin)
        origin = normalize_origin(origin)
        pick = _single_pick(origin, crm_picks)
        if pick and not self.sale_order_id:
            synced = self._hlv_order_from_ref(origin, crm_picks)
            if synced:
                self._hlv_link_sale_order(synced, self._hlv_live_requests(), self.env.user.partner_id)
            else:
                self.write({"crm_sale_order_id": pick[0], "crm_sale_order_code": pick[1]})
        if self.crm_sale_order_code and (self.sale_order_id or self.crm_sale_order_code not in origin.split(", ")):
            self.write({"crm_sale_order_id": False, "crm_sale_order_code": False})
        return orders

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
