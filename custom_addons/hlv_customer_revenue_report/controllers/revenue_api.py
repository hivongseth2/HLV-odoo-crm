# -*- coding: utf-8 -*-
"""
API công khai (HTTP) cho báo cáo Doanh thu theo khách hàng.

Xác thực: header `X-Revenue-Token: <token>` (hoặc query param `token`). Token so sánh với
System Parameter `hlv_customer_revenue_report.api_token` - vào Settings > Technical >
Parameters > System Parameters, tạo key trên với giá trị token tự chọn trước khi dùng API.

Mỗi endpoint hỗ trợ ĐỒNG THỜI 3 trục lọc theo ngày, độc lập với nhau (kết hợp AND nếu
truyền nhiều trục cùng lúc):
    - date_from / date_to              : ngày xuất kho (stock.picking.date_done)
    - order_date_from / order_date_to  : ngày đặt hàng gốc trên Odoo (sale.order.date_order)
    - misa_order_date_from / misa_order_date_to : ngày đơn hàng ghi nhận trên MISA
      (sale.order.x_studio_misa_order_date - có thể khác order_date do backdating khi sync)

Endpoints:
    GET /api/revenue/monthly
        ?date_from=2026-05-01&date_to=2026-07-31&date_field=date_done
        (+ search, shopee_filter, order_date_from/to, misa_order_date_from/to)
        -> {"ok": true, "rows": [{"month_label": "2026-05", "order_count": 120,
             "customer_count": 45, "qty_delivered": ..., "amount_net": ..., ...}, ...]}
        Tổng CỘNG GỘP TẤT CẢ khách hàng/shop theo từng tháng - dùng cho câu hỏi kiểu
        "công ty bán ra bao nhiêu mỗi tháng trong khoảng T5-T7" (không tách theo khách hàng).
        date_field chọn cột nào định nghĩa "tháng": date_done (mặc định, ngày xuất kho),
        order_date (ngày đặt hàng Odoo) hoặc misa_order_date (ngày đơn hàng MISA) - nên đặt
        trùng với trục đang lọc (date_from/to hay order_date_from/to...) để tháng hiển thị
        đúng ý muốn.

    GET /api/revenue/customers
        ?date_from=2026-01-01&date_to=2026-01-31&search=BM&shopee_filter=all
        &order_date_from=...&order_date_to=...&misa_order_date_from=...&misa_order_date_to=...
        &order_by=amount_net&order_dir=desc&limit=50&offset=0
        -> {"ok": true, "rows": [...], "total_count": N}
        Danh sách TỪNG khách hàng/shop (có phân trang) - dùng khi cần breakdown theo khách hàng.

    GET /api/revenue/customers/monthly?group_type=partner&group_id=123&date_from=&date_to=
        (+ order_date_from/to, misa_order_date_from/to nếu cần)
        -> {"ok": true, "rows": [...]}

    GET /api/revenue/customers/detail?group_type=partner&group_id=123&date_from=...&date_to=...
        (+ order_date_from/to, misa_order_date_from/to - nên truyền lại giống lúc gọi /monthly
        để tổng số khớp với dòng tháng đã lấy)
        -> {"ok": true, "rows": [...]}
        date_from/date_to là 2 đầu mút BAO GỒM (inclusive) - nên lấy nguyên date_from/date_to
        của dòng tháng trả về bởi /customers/monthly, KHÔNG tự đoán ngày cuối tháng.
        Đây chính là danh sách TẤT CẢ đơn hàng của 1 khách hàng trong 1 tháng/khoảng ngày.

    GET /api/revenue/order/lines
        ?order_name=DH125524949234726
        HOẶC ?group_type=partner&group_id=123&date_from=...&date_to=...
        (+ order_date_from/to, misa_order_date_from/to; limit, offset nếu dùng group_id)
        -> {"ok": true, "rows": [{"sale_order_name": "...", "product_name": "...",
             "product_code": "...", "qty_delivered": ..., "price_unit_after_tax": ...,
             "amount_gross": ..., "amount_returned": ..., "amount_net": ...}, ...], "total_count": N}
        Chi tiết TỪNG DÒNG SẢN PHẨM (giá, số lượng, thành tiền...) - khác /customers/detail
        (chỉ tổng theo đơn hàng). Truyền order_name để xem đúng 1 đơn hàng, hoặc group_id +
        khoảng ngày để xem tất cả dòng sản phẩm của 1 khách hàng/shop trong khoảng đó.

    GET /api/revenue/customers/export
        ?date_from=...&date_to=...&search=...&shopee_filter=...
        (+ order_date_from/to, misa_order_date_from/to; thêm group_type=partner|shop&group_id=123
        để xuất riêng 1 khách hàng/shop)
        -> tải trực tiếp file .xlsx

group_type: "partner" (khách hàng thật) hoặc "shop" (shop Shopee - đơn Shopee được gộp
theo shop thay vì theo contact chung chung, xem models/customer_revenue_report.py).
"""

import json
import logging

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

TOKEN_PARAM = "hlv_customer_revenue_report.api_token"


class HlvRevenueApiController(http.Controller):

    # ==================== Helpers ====================
    def _authenticate(self, token):
        expected = request.env["ir.config_parameter"].sudo().get_param(TOKEN_PARAM, default="")
        if not expected:
            _logger.error("%s chưa được cấu hình trong System Parameters.", TOKEN_PARAM)
            return False, {
                "ok": False, "error": "server_misconfigured",
                "message": 'Server chưa cấu hình System Parameter "%s".' % TOKEN_PARAM,
            }
        if not token or token != expected:
            return False, {"ok": False, "error": "invalid_token", "message": "Token không hợp lệ."}
        return True, None

    def _extract_token(self, kwargs):
        return (kwargs.get("token") or request.httprequest.headers.get("X-Revenue-Token") or "").strip()

    def _json_response(self, payload, status=200):
        return request.make_response(
            json.dumps(payload, ensure_ascii=False),
            headers=[("Content-Type", "application/json")],
            status=status,
        )

    def _report_model(self):
        return request.env["hlv.customer.revenue.report"].sudo()

    def _to_int(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _extra_date_kwargs(self, kwargs):
        return {
            "order_date_from": kwargs.get("order_date_from") or False,
            "order_date_to": kwargs.get("order_date_to") or False,
            "misa_order_date_from": kwargs.get("misa_order_date_from") or False,
            "misa_order_date_to": kwargs.get("misa_order_date_to") or False,
        }

    # ==================== Endpoints ====================
    @http.route("/api/revenue/monthly", type="http", auth="none", methods=["GET"], csrf=False, cors="*")
    def api_revenue_monthly(self, **kwargs):
        """Tổng doanh thu theo tháng, CỘNG GỘP tất cả khách hàng/shop (không breakdown)."""
        ok, err = self._authenticate(self._extract_token(kwargs))
        if not ok:
            return self._json_response(err, 401)

        rows = self._report_model().get_overall_monthly_summary(
            date_from=kwargs.get("date_from") or False,
            date_to=kwargs.get("date_to") or False,
            search=kwargs.get("search") or False,
            shopee_filter=kwargs.get("shopee_filter") or "all",
            date_field=kwargs.get("date_field") or "date_done",
            **self._extra_date_kwargs(kwargs),
        )
        return self._json_response({"ok": True, "rows": rows})

    @http.route("/api/revenue/customers", type="http", auth="none", methods=["GET"], csrf=False, cors="*")
    def api_revenue_customers(self, **kwargs):
        ok, err = self._authenticate(self._extract_token(kwargs))
        if not ok:
            return self._json_response(err, 401)

        limit = self._to_int(kwargs.get("limit")) or 50
        offset = self._to_int(kwargs.get("offset")) or 0

        result = self._report_model().get_customers_summary(
            date_from=kwargs.get("date_from") or False,
            date_to=kwargs.get("date_to") or False,
            search=kwargs.get("search") or False,
            shopee_filter=kwargs.get("shopee_filter") or "all",
            order_by=kwargs.get("order_by") or "amount_net",
            order_dir=kwargs.get("order_dir") or "desc",
            limit=limit,
            offset=offset,
            **self._extra_date_kwargs(kwargs),
        )
        return self._json_response({"ok": True, "rows": result["rows"], "total_count": result["total_count"]})

    @http.route("/api/revenue/customers/monthly", type="http", auth="none", methods=["GET"], csrf=False, cors="*")
    def api_revenue_customer_monthly(self, **kwargs):
        ok, err = self._authenticate(self._extract_token(kwargs))
        if not ok:
            return self._json_response(err, 401)

        group_id = self._to_int(kwargs.get("group_id"))
        if not group_id:
            return self._json_response({"ok": False, "error": "missing_group_id", "message": "Thiếu group_id."}, 400)

        try:
            rows = self._report_model().get_group_monthly_summary(
                kwargs.get("group_type") or "partner", group_id,
                date_from=kwargs.get("date_from") or False,
                date_to=kwargs.get("date_to") or False,
                **self._extra_date_kwargs(kwargs),
            )
        except UserError as e:
            return self._json_response({"ok": False, "error": "invalid_request", "message": str(e)}, 400)
        return self._json_response({"ok": True, "rows": rows})

    @http.route("/api/revenue/customers/detail", type="http", auth="none", methods=["GET"], csrf=False, cors="*")
    def api_revenue_customer_detail(self, **kwargs):
        ok, err = self._authenticate(self._extract_token(kwargs))
        if not ok:
            return self._json_response(err, 401)

        group_id = self._to_int(kwargs.get("group_id"))
        date_from = kwargs.get("date_from")
        date_to = kwargs.get("date_to")
        if not group_id or not date_from or not date_to:
            return self._json_response({
                "ok": False, "error": "missing_params", "message": "Thiếu group_id / date_from / date_to.",
            }, 400)

        try:
            rows = self._report_model().get_group_month_detail(
                kwargs.get("group_type") or "partner", group_id, date_from, date_to,
                **self._extra_date_kwargs(kwargs),
            )
        except UserError as e:
            return self._json_response({"ok": False, "error": "invalid_request", "message": str(e)}, 400)
        return self._json_response({"ok": True, "rows": rows})

    @http.route("/api/revenue/order/lines", type="http", auth="none", methods=["GET"], csrf=False, cors="*")
    def api_revenue_order_lines(self, **kwargs):
        """Chi tiết từng dòng sản phẩm - theo order_name HOẶC theo group_id + khoảng ngày."""
        ok, err = self._authenticate(self._extract_token(kwargs))
        if not ok:
            return self._json_response(err, 401)

        limit = self._to_int(kwargs.get("limit")) or 500
        offset = self._to_int(kwargs.get("offset")) or 0

        try:
            result = self._report_model().get_order_lines_detail(
                order_name=kwargs.get("order_name") or False,
                group_type=kwargs.get("group_type") or "partner",
                group_id=self._to_int(kwargs.get("group_id")),
                date_from=kwargs.get("date_from") or False,
                date_to=kwargs.get("date_to") or False,
                limit=limit,
                offset=offset,
                **self._extra_date_kwargs(kwargs),
            )
        except UserError as e:
            return self._json_response({"ok": False, "error": "invalid_request", "message": str(e)}, 400)
        return self._json_response({"ok": True, "rows": result["rows"], "total_count": result["total_count"]})

    @http.route("/api/revenue/customers/export", type="http", auth="none", methods=["GET"], csrf=False, cors="*")
    def api_revenue_customers_export(self, **kwargs):
        ok, err = self._authenticate(self._extract_token(kwargs))
        if not ok:
            return self._json_response(err, 401)

        report = self._report_model()
        group_id = self._to_int(kwargs.get("group_id"))
        try:
            if group_id:
                attachment_id = report.export_group_revenue_excel(
                    kwargs.get("group_type") or "partner", group_id,
                    date_from=kwargs.get("date_from") or False,
                    date_to=kwargs.get("date_to") or False,
                    **self._extra_date_kwargs(kwargs),
                )
            else:
                attachment_id = report.export_customers_summary_excel(
                    date_from=kwargs.get("date_from") or False,
                    date_to=kwargs.get("date_to") or False,
                    search=kwargs.get("search") or False,
                    shopee_filter=kwargs.get("shopee_filter") or "all",
                    **self._extra_date_kwargs(kwargs),
                )
        except UserError as e:
            return self._json_response({"ok": False, "error": "invalid_request", "message": str(e)}, 400)

        attachment = request.env["ir.attachment"].sudo().browse(attachment_id)
        return request.make_response(
            attachment.raw,
            headers=[
                ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                ("Content-Disposition", 'attachment; filename="%s"' % attachment.name),
            ],
        )
