# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import hashlib
import hmac
import logging
import requests

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    x_is_zalo_order = fields.Boolean(
        string="Đơn hàng Zalo Mini App",
        related="partner_id.x_is_zalo_account",
        store=True,
    )

    # ===== Zalo Checkout SDK Transaction Fields =====
    x_zalo_trans_id = fields.Char(
        string="Mã giao dịch Zalo SDK",
        help="Mã định danh giao dịch trả về từ Zalo Checkout SDK hoặc Cổng thanh toán",
        index=True,
    )
    x_zalo_payment_method = fields.Char(
        string="Phương thức thanh toán Zalo",
        help="Phương thức thanh toán do Checkout SDK ghi nhận (VD: ZALOPAY_SANDBOX, VNPAY_SANDBOX, COD)",
    )
    x_zalo_payment_status = fields.Selection(
        [
            ("pending", "Chờ thanh toán"),
            ("paid", "Đã thanh toán"),
            ("failed", "Thanh toán thất bại"),
            ("cancelled", "Đã hủy đơn"),
        ],
        string="Trạng thái thanh toán Zalo",
        default="pending",
        index=True,
    )
    x_zalo_trans_time = fields.Datetime(
        string="Thời điểm giao dịch Zalo",
        help="Thời gian hoàn tất giao dịch thanh toán phía Zalo SDK",
    )
    x_zalo_order_id = fields.Char(
        string="Mã đơn Zalo SDK",
        help="orderId do Zalo Checkout SDK sinh ra trong createOrder, dùng để map callback/notify với đơn Odoo",
        index=True,
    )

    # ===== Zalo Checkout SDK Refund Fields =====
    x_zalo_refund_id = fields.Char(
        string="Mã hoàn tiền Zalo",
        help="refundId do Zalo Checkout SDK trả về khi gọi createRefund",
        index=True,
    )
    x_zalo_refund_status = fields.Selection(
        [
            ("pending", "Đang hoàn tiền"),
            ("success", "Hoàn tiền thành công"),
            ("failed", "Hoàn tiền thất bại"),
        ],
        string="Trạng thái hoàn tiền Zalo",
        default=False,
        index=True,
    )
    x_zalo_refund_amount = fields.Float(
        string="Số tiền đã hoàn Zalo",
        help="Số tiền đã gửi yêu cầu hoàn qua Zalo Checkout SDK",
    )
    x_zalo_refund_time = fields.Datetime(
        string="Thời điểm hoàn tiền Zalo",
        help="Thời gian Zalo xác nhận hoàn tiền thành công",
    )
    x_zalo_refund_log = fields.Text(
        string="Log hoàn tiền Zalo",
        help="Nhật ký phản hồi từ Zalo Refund API",
    )


    # Computed fields tổng hợp từ picking_ids để đảm bảo 100% tương thích REST API cũ
    x_return_requested = fields.Boolean(
        string="Khách đề nghị đổi/trả",
        compute="_compute_zalo_return_summary",
        search="_search_x_return_requested",
        help="Khách hàng Zalo Mini App đã gửi yêu cầu đổi/trả cho ít nhất 1 phiếu giao hàng",
    )

    x_return_state = fields.Selection(
        [
            ("pending", "Chờ duyệt"),
            ("approved", "Đã duyệt"),
            ("processing", "Đang xử lý"),
            ("completed", "Hoàn tất"),
            ("rejected", "Từ chối"),
            ("cancelled", "Đã thu hồi"),
        ],
        string="Trạng thái đổi/trả",
        compute="_compute_zalo_return_summary",
        help="Trạng thái tổng hợp của các phiếu đổi/trả thuộc đơn Zalo",
    )

    x_return_count = fields.Integer(
        string="Số lần gửi đổi/trả",
        compute="_compute_zalo_return_summary",
        help="Tổng số lần gửi yêu cầu đổi/trả của các phiếu kho",
    )

    x_return_revoke_count = fields.Integer(
        string="Số lần thu hồi đổi/trả",
        compute="_compute_zalo_return_summary",
        help="Tổng số lần thu hồi đổi/trả của các phiếu kho",
    )

    x_return_type = fields.Selection(
        [
            ("return", "Trả hàng hoàn tiền"),
            ("exchange", "Đổi hàng"),
            ("refund", "Hoàn tiền một phần"),
        ],
        string="Loại đổi/trả",
        compute="_compute_zalo_return_summary",
        help="Phân loại đổi/trả của phiếu xuất kho Zalo",
    )

    x_return_picking_id = fields.Many2one(
        "stock.picking",
        string="Phiếu trả hàng",
        compute="_compute_zalo_return_summary",
        help="Phiếu nhập kho trả hàng (WH/IN) mới nhất từ phiếu xuất kho Zalo",
    )

    x_return_refund_amount = fields.Float(
        string="Số tiền hoàn lại",
        compute="_compute_zalo_return_summary",
        help="Tổng số tiền hoàn lại của các phiếu kho Zalo",
    )

    x_return_rejected_reason = fields.Text(
        string="Lý do từ chối",
        compute="_compute_zalo_return_summary",
        help="Lý do từ chối yêu cầu đổi/trả Zalo",
    )

    x_return_completed_date = fields.Datetime(
        string="Ngày hoàn tất đổi/trả",
        compute="_compute_zalo_return_summary",
        help="Thời điểm hoàn tất xử lý đổi/trả gần nhất",
    )

    x_return_picking_count = fields.Integer(
        string="Số phiếu đổi/trả",
        compute="_compute_zalo_return_summary",
    )

    x_is_returnable = fields.Boolean(
        string="Có thể yêu cầu đổi/trả",
        compute="_compute_zalo_return_eligibility",
        help="Đơn hàng đã giao thành công trong vòng 7 ngày và có thể gửi yêu cầu đổi/trả",
    )

    x_days_since_delivery = fields.Integer(
        string="Số ngày từ khi nhận hàng",
        compute="_compute_zalo_return_eligibility",
    )

    x_return_category = fields.Selection(
        [
            ("supplier_fault", "Lỗi nhà cung cấp / Vận chuyển"),
            ("customer_demand", "Đổi trả theo nhu cầu"),
        ],
        string="Nhóm nguyên nhân đổi/trả",
        compute="_compute_zalo_return_summary",
    )

    x_product_condition = fields.Selection(
        [
            ("unused", "Chưa qua sử dụng (nguyên tem)"),
            ("used", "Đã qua sử dụng"),
        ],
        string="Tình trạng sản phẩm",
        compute="_compute_zalo_return_summary",
    )

    @api.depends(
        "write_date",
        "picking_ids.state",
        "picking_ids.date_done",
        "picking_ids.x_zalo_return_count",
        "picking_ids.x_zalo_return_revoke_count",
        "state",
    )
    def _compute_zalo_return_eligibility(self):
        now = fields.Datetime.now()
        for order in self:
            ret_count = sum(order.picking_ids.mapped("x_zalo_return_count"))
            revoke_count = sum(order.picking_ids.mapped("x_zalo_return_revoke_count"))
            limit_reached = (revoke_count >= 2) or (revoke_count >= 1 and ret_count >= 2)

            out_pickings = order.picking_ids.filtered(lambda p: p.picking_type_id.code == "outgoing" and p.state == "done")
            if out_pickings:
                done_dates = [p.date_done for p in out_pickings if p.date_done]
                last_done = max(done_dates) if done_dates else order.write_date
                delta = (now - last_done).days if last_done else 0
                order.x_days_since_delivery = max(0, delta)
                order.x_is_returnable = (delta <= 7) and not limit_reached
            elif order.state in ("sale", "done"):
                order.x_days_since_delivery = 0
                order.x_is_returnable = not limit_reached
            else:
                order.x_days_since_delivery = 0
                order.x_is_returnable = False

    @api.depends(
        "picking_ids.picking_type_id.code",
        "picking_ids.x_zalo_return_requested",
        "picking_ids.x_zalo_return_state",
        "picking_ids.x_zalo_return_type",
        "picking_ids.x_zalo_return_refund_amount",
        "picking_ids.x_zalo_return_picking_id",
        "picking_ids.x_zalo_return_rejected_reason",
        "picking_ids.x_zalo_return_completed_date",
        "picking_ids.x_zalo_return_category",
        "picking_ids.x_zalo_product_condition",
        "picking_ids.x_zalo_return_count",
        "picking_ids.x_zalo_return_revoke_count",
    )
    def _compute_zalo_return_summary(self):
        for order in self:
            order.x_return_count = sum(order.picking_ids.mapped("x_zalo_return_count"))
            order.x_return_revoke_count = sum(order.picking_ids.mapped("x_zalo_return_revoke_count"))

            return_pickings = order.picking_ids.filtered(
                lambda p: p.picking_type_id.code == "outgoing" and p.x_zalo_return_requested
            )
            order.x_return_requested = bool(return_pickings)
            order.x_return_picking_count = len(return_pickings)

            if not return_pickings:
                order.x_return_state = False
                order.x_return_type = False
                order.x_return_picking_id = False
                order.x_return_refund_amount = 0.0
                order.x_return_rejected_reason = False
                order.x_return_completed_date = False
                order.x_return_category = False
                order.x_product_condition = False
                continue

            states = return_pickings.mapped("x_zalo_return_state")
            if "pending" in states:
                order.x_return_state = "pending"
            elif "approved" in states:
                order.x_return_state = "approved"
            elif "processing" in states:
                order.x_return_state = "processing"
            elif "completed" in states:
                order.x_return_state = "completed"
            elif "rejected" in states:
                order.x_return_state = "rejected"
            else:
                order.x_return_state = "pending"

            latest = return_pickings[0]
            order.x_return_type = latest.x_zalo_return_type
            order.x_return_category = latest.x_zalo_return_category
            order.x_product_condition = latest.x_zalo_product_condition

            valid_return_pickings = return_pickings.filtered(lambda p: p.x_zalo_return_picking_id)
            order.x_return_picking_id = valid_return_pickings[0].x_zalo_return_picking_id if valid_return_pickings else False

            order.x_return_refund_amount = sum(return_pickings.mapped("x_zalo_return_refund_amount"))

            reasons = [r for r in return_pickings.mapped("x_zalo_return_rejected_reason") if r]
            order.x_return_rejected_reason = "\n".join(reasons) if reasons else False

            completed_dates = [d for d in return_pickings.mapped("x_zalo_return_completed_date") if d]
            order.x_return_completed_date = max(completed_dates) if completed_dates else False

    def _search_x_return_requested(self, operator, value):
        if operator in ("=", "!=") and isinstance(value, bool):
            if (operator == "=" and value) or (operator == "!=" and not value):
                return [("picking_ids.picking_type_id.code", "=", "outgoing"), ("picking_ids.x_zalo_return_requested", "=", True)]
            else:
                return [("picking_ids.picking_type_id.code", "=", "outgoing"), ("picking_ids.x_zalo_return_requested", "=", False)]
        return []

    def _is_zalo_order(self):
        """Kiểm tra đơn hàng có phải từ Zalo Mini App không."""
        self.ensure_one()
        return bool(self.partner_id.x_is_zalo_account)

    def action_view_zalo_return_pickings(self):
        """Smart button xem danh sách các phiếu xuất kho Zalo có yêu cầu đổi/trả."""
        self.ensure_one()
        action = self.env.ref("stock.action_picking_tree_all").read()[0]
        return_pickings = self.picking_ids.filtered(
            lambda p: p.picking_type_id.code == "outgoing" and p.x_zalo_return_requested
        )
        action["domain"] = [("id", "in", return_pickings.ids)]
        action["context"] = {"default_sale_id": self.id}
        return action

    def _send_zalo_cod_callback_payment(self, result_code=1):
        """
        Gọi Server-to-Server API của Zalo:
          POST https://payment-mini.zalo.me/api/transaction/{appId}/cod-callback-payment
        để cập nhật trạng thái giao dịch COD trên Zalo Developer Portal từ "Chờ xử lý" -> "Thành công" (resultCode=1).
        """
        import requests
        import hmac
        import hashlib

        ICP = self.env["ir.config_parameter"].sudo()
        app_id = str(ICP.get_param("hlv_zalo_miniapp.checkout_app_id", "") or ICP.get_param("zalo.checkout_app_id", "")).strip()
        private_key = str(
            ICP.get_param("hlv_zalo_miniapp.checkout_private_key", "")
            or ICP.get_param("checkout_private_key", "")
            or ICP.get_param("zalo.checkout_private_key", "")
        ).strip()

        for order in self:
            zalo_order_id = (order.x_zalo_order_id or "").strip()
            if not zalo_order_id or not app_id or not private_key:
                _logger.warning("Bỏ qua gọi Zalo COD Callback Payment cho đơn %s: Thiếu app_id/private_key/x_zalo_order_id", order.name)
                continue

            # 1. Tính toán MAC: appId={appId}&orderId={orderId}&resultCode={resultCode}&privateKey={privateKey}
            raw_mac_str = f"appId={app_id}&orderId={zalo_order_id}&resultCode={result_code}&privateKey={private_key}"
            mac = hmac.new(
                private_key.encode("utf-8"),
                raw_mac_str.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

            endpoint_url = f"https://payment-mini.zalo.me/api/transaction/{app_id}/cod-callback-payment"
            payload = {
                "appId": app_id,
                "orderId": zalo_order_id,
                "resultCode": result_code,
                "mac": mac,
            }
            headers = {"Content-Type": "application/json"}

            try:
                _logger.info("Đang gọi Zalo COD Callback Payment API cho đơn %s (orderId=%s) tại %s...", order.name, zalo_order_id, endpoint_url)
                resp = requests.post(endpoint_url, json=payload, headers=headers, timeout=10)
                _logger.info("Kết quả Zalo COD Callback Payment: HTTP %s - Body: %s", resp.status_code, resp.text)
                
                # Nếu Zalo yêu cầu MAC dạng không chứa &privateKey= ở đuôi, fallback thử thêm format 2:
                if resp.status_code != 200 or '"error":-2101' in resp.text or '"err":-2101' in resp.text:
                    raw_mac_str2 = f"appId={app_id}&orderId={zalo_order_id}&resultCode={result_code}"
                    mac2 = hmac.new(private_key.encode("utf-8"), raw_mac_str2.encode("utf-8"), hashlib.sha256).hexdigest()
                    payload["mac"] = mac2
                    resp2 = requests.post(endpoint_url, json=payload, headers=headers, timeout=10)
                    _logger.info("Kết quả Zalo COD Callback Payment (Format 2): HTTP %s - Body: %s", resp2.status_code, resp2.text)
            except Exception as req_err:
                _logger.error("Lỗi khi gọi Zalo COD Callback Payment cho đơn %s: %s", order.name, str(req_err))

    def action_mark_zalo_paid(self):
        """
        Nút bấm trên giao diện Odoo cho phép nhân viên xác nhận đã thu tiền đơn COD
        hoặc đơn hàng Zalo Mini App.
        Tự động chuyển state -> sale (nếu draft), cập nhật x_zalo_payment_status = 'paid'
        và tự động gọi API Zalo payment-mini cod-callback-payment để cập nhật trạng thái trên Zalo Portal sang 'Thành công'.
        """
        for order in self:
            if order.state == "draft":
                try:
                    order.action_confirm()
                except Exception as e:
                    _logger.warning("Không thể tự động confirm đơn %s: %s", order.name, str(e))
            order.write({
                "x_zalo_payment_status": "paid",
                "x_zalo_trans_time": fields.Datetime.now(),
            })
            order._send_zalo_cod_callback_payment(result_code=1)
        return True

    def action_mark_zalo_cancelled(self):
        """
        Nút bấm trên giao diện Odoo cho phép nhân viên xác nhận đơn hàng Zalo/COD đã bị hủy,
        gọi API Zalo payment-mini cod-callback-payment với resultCode = -1 để đồng bộ trạng thái.
        """
        for order in self:
            order.write({
                "x_zalo_payment_status": "cancelled",
            })
            order._send_zalo_cod_callback_payment(result_code=-1)
        return True

    def action_cancel(self):
        """Override action_cancel để đồng bộ trạng thái hủy đơn lên Zalo Developer Portal."""
        res = super().action_cancel()
        for order in self:
            if order.x_zalo_order_id:
                order.write({
                    "x_zalo_payment_status": "cancelled",
                })
                try:
                    order._send_zalo_cod_callback_payment(result_code=-1)
                except Exception as ce:
                    _logger.warning("Không thể gửi Zalo cancel callback cho đơn %s: %s", order.name, ce)
        return res

    def action_query_zalo_order_status(self):
        """
        Gửi yêu cầu Server-to-Server API getOrderStatus sang Zalo SDK Server
        để tra cứu trạng thái giao dịch thực tế của đơn hàng.
        Endpoint: https://payment-mini.zalo.me/api/transaction/get-status (HTTP GET)
        """
        import requests
        import hmac
        import hashlib
        import json

        ICP = self.env["ir.config_parameter"].sudo()
        app_id = str(ICP.get_param("hlv_zalo_miniapp.checkout_app_id", "") or ICP.get_param("zalo.checkout_app_id", "")).strip()
        private_key = str(
            ICP.get_param("hlv_zalo_miniapp.checkout_private_key", "")
            or ICP.get_param("checkout_private_key", "")
            or ICP.get_param("zalo.checkout_private_key", "")
        ).strip()

        for order in self:
            zalo_order_id = (order.x_zalo_order_id or "").strip()
            if not zalo_order_id:
                raise UserError(_("Đơn hàng này chưa có Mã đơn Zalo SDK (x_zalo_order_id)."))

            if not app_id or not private_key:
                raise UserError(_("Chưa cấu hình Zalo App ID hoặc Private Key trong Odoo System Parameters."))

            # MAC formula: appId={appId}&orderId={orderId}&privateKey={privateKey}
            raw_mac_str = f"appId={app_id}&orderId={zalo_order_id}&privateKey={private_key}"
            mac = hmac.new(
                private_key.encode("utf-8"),
                raw_mac_str.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

            target_url = "https://payment-mini.zalo.me/api/transaction/get-status"
            params = {
                "appId": app_id,
                "orderId": zalo_order_id,
                "mac": mac,
            }
            headers = {"Content-Type": "application/json"}

            try:
                _logger.info("Đang tra cứu getOrderStatus (GET) cho đơn %s (orderId=%s)...", order.name, zalo_order_id)
                resp = requests.get(target_url, params=params, headers=headers, timeout=10)
                _logger.info("Kết quả getOrderStatus (GET): HTTP %s - Body: %s", resp.status_code, resp.text)

                # Thử POST nếu GET trả về lỗi hoặc rỗng
                if resp.status_code != 200 or not resp.text or not resp.text.strip():
                    _logger.info("Thử lại getOrderStatus bằng POST cho đơn %s...", order.name)
                    resp = requests.post(target_url, json=params, headers=headers, timeout=10)
                    _logger.info("Kết quả getOrderStatus (POST): HTTP %s - Body: %s", resp.status_code, resp.text)

                res_json = {}
                if resp.text and resp.text.strip():
                    try:
                        res_json = resp.json()
                    except Exception as json_err:
                        _logger.warning("Không thể parse JSON từ Zalo response: %s (Lỗi: %s)", resp.text, str(json_err))

                if resp.status_code == 200 and res_json:
                    return_code = res_json.get("returnCode")
                    data = res_json.get("data", {})
                    result_code = data.get("resultCode") if isinstance(data, dict) else res_json.get("resultCode")
                    trans_id = data.get("transId") if isinstance(data, dict) else res_json.get("transId")
                    message = (data.get("message") if isinstance(data, dict) else False) or res_json.get("returnMessage") or res_json.get("message") or ""

                    vals = {}
                    if trans_id:
                        vals["x_zalo_trans_id"] = str(trans_id)

                    if result_code == 1 or return_code == 1:
                        vals["x_zalo_payment_status"] = "paid"
                        vals["x_zalo_trans_time"] = fields.Datetime.now()
                        if order.state == "draft":
                            try:
                                order.action_confirm()
                            except Exception:
                                pass
                        msg = _("Tra cứu Zalo getOrderStatus: Giao dịch THÀNH CÔNG (resultCode=1, transId=%s).") % (trans_id or "")
                    elif result_code == 0 or return_code == 0:
                        vals["x_zalo_payment_status"] = "pending"
                        msg = _("Tra cứu Zalo getOrderStatus: Giao dịch CHỜ XỬ LÝ (resultCode=0).")
                    elif result_code == -1 or return_code == -1:
                        vals["x_zalo_payment_status"] = "failed"
                        msg = _("Tra cứu Zalo getOrderStatus: Giao dịch THẤT BẠI (resultCode=-1, message=%s).") % message
                    else:
                        msg = _("Tra cứu Zalo getOrderStatus: Phản hồi Zalo = %s") % resp.text

                    if vals:
                        order.write(vals)

            except Exception as req_err:
                _logger.exception("Lỗi khi tra cứu getOrderStatus cho đơn %s: %s", order.name, str(req_err))
                raise UserError(_("Lỗi kết nối tới Zalo SDK Server: %s") % str(req_err))
        return True


    @api.model
    def cron_sync_pending_zalo_orders(self):
        """
        Cronjob tự động chạy ngầm trong Odoo (15 phút/lần).
        Tự động tìm tất cả các đơn hàng Zalo có x_zalo_payment_status = 'pending'
        và gọi getOrderStatus sang Zalo SDK Server để đồng bộ trạng thái tự động 100%.
        """
        pending_orders = self.search(
            [
                ("x_zalo_payment_status", "=", "pending"),
                ("x_zalo_order_id", "!=", False),
                ("x_zalo_order_id", "!=", ""),
            ],
            limit=50,
        )
        _logger.info("Zalo Auto Sync Cronjob: Đang quét %s đơn hàng chờ thanh toán...", len(pending_orders))
        for order in pending_orders:
            try:
                order.action_query_zalo_order_status()
            except Exception as e:
                _logger.warning("Zalo Auto Sync Cronjob lỗi ở đơn %s: %s", order.name, str(e))
        return True







    # ============================================================
    # Zalo Checkout SDK Refund APIs
    # ============================================================

    def _get_zalo_checkout_credentials(self):
        """Lấy App ID và Private Key từ ir.config_parameter."""
        ICP = self.env["ir.config_parameter"].sudo()
        app_id = str(ICP.get_param("hlv_zalo_miniapp.checkout_app_id", "") or "").strip()
        private_key = str(
            ICP.get_param("hlv_zalo_miniapp.checkout_private_key", "")
            or ICP.get_param("checkout_private_key", "")
            or ICP.get_param("zalo.checkout_private_key", "")
        ).strip()
        return app_id, private_key

    def _can_create_zalo_refund(self):
        """Kiểm tra đơn hàng có đủ điều kiện gọi Zalo refund không."""
        self.ensure_one()
        if not self.x_zalo_trans_id:
            return False, _("Đơn hàng không có mã giao dịch Zalo (x_zalo_trans_id).")
        if self.x_zalo_payment_status != "paid":
            return False, _("Giao dịch chưa được thanh toán.")
        if self.x_zalo_payment_method and "COD" in self.x_zalo_payment_method.upper():
            return False, _("Đơn COD không cần hoàn tiền qua Zalo.")
        return True, ""

    def action_create_zalo_refund(self, refund_amount=None):
        """
        Gọi Zalo Checkout SDK createRefund API để hoàn tiền.
        Docs: https://docs.zaloplatforms.com/docs/MA/checkoutSdk/apis/createRefund
        """
        self.ensure_one()
        order = self

        can_refund, msg = order._can_create_zalo_refund()
        if not can_refund:
            raise UserError(msg)

        app_id, private_key = order._get_zalo_checkout_credentials()
        if not app_id or not private_key:
            raise UserError(_("Chưa cấu hình Zalo App ID hoặc Private Key trong Odoo System Parameters."))

        # Tính số tiền hoàn: ưu tiên tham số, sau đó đến x_return_refund_amount, cuối cùng là amount_total
        amount = refund_amount
        if amount is None or amount <= 0:
            amount = order.x_return_refund_amount or 0.0
        if amount <= 0:
            amount = order.amount_total or 0.0
        if amount <= 0:
            raise UserError(_("Số tiền hoàn phải lớn hơn 0."))

        # Zalo yêu cầu amount là số nguyên (VND)
        amount_int = int(round(amount))

        # Kiểm tra tổng số tiền đã hoàn không vượt quá tổng đơn
        already_refunded = sum(
            order.picking_ids.filtered(lambda p: p.x_zalo_refund_status == "success").mapped("x_zalo_refund_amount")
        ) or 0.0
        if already_refunded + amount_int > (order.amount_total or 0.0):
            raise UserError(_("Tổng số tiền hoàn không được vượt quá tổng giá trị đơn hàng."))

        description = f"Hoan tien don hang {order.name}"
        raw_mac_str = (
            f"appId={app_id}&transId={order.x_zalo_trans_id}&amount={amount_int}"
            f"&description={description}&privateKey={private_key}"
        )
        mac = hmac.new(
            private_key.encode("utf-8"),
            raw_mac_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        payload = {
            "appId": app_id,
            "transId": order.x_zalo_trans_id,
            "amount": amount_int,
            "description": description,
            "mac": mac,
        }
        headers = {"Content-Type": "application/json"}

        try:
            _logger.info("Gọi Zalo createRefund cho đơn %s (transId=%s, amount=%s)...", order.name, order.x_zalo_trans_id, amount_int)
            resp = requests.post("https://payment-mini.zalo.me/api/refund/create", json=payload, headers=headers, timeout=10)
            _logger.info("Kết quả Zalo createRefund đơn %s: HTTP %s - Body: %s", order.name, resp.status_code, resp.text)
        except Exception as req_err:
            _logger.exception("Lỗi kết nối Zalo createRefund cho đơn %s: %s", order.name, str(req_err))
            raise UserError(_("Lỗi kết nối tới Zalo Refund API: %s") % str(req_err))

        res_json = {}
        if resp.text and resp.text.strip():
            try:
                res_json = resp.json()
            except Exception as json_err:
                _logger.warning("Không thể parse JSON từ Zalo createRefund response: %s (Lỗi: %s)", resp.text, str(json_err))

        refund_id = res_json.get("refundId")
        return_code = res_json.get("returnCode")
        return_message = res_json.get("returnMessage", "")

        if return_code == 1:
            status = "success"
        elif return_code > 1:
            status = "pending"
        else:
            status = "failed"

        vals = {
            "x_zalo_refund_id": refund_id,
            "x_zalo_refund_status": status,
            "x_zalo_refund_amount": amount_int if status in ("success", "pending") else 0.0,
            "x_zalo_refund_time": fields.Datetime.now() if status == "success" else False,
            "x_zalo_refund_log": (
                f"[createRefund] HTTP={resp.status_code}, returnCode={return_code}, "
                f"returnMessage={return_message}, refundId={refund_id}, raw={resp.text}"
            ),
        }
        order.write(vals)

        # Đồng bộ refund info sang các phiếu xuất kho đang return
        return_pickings = order.picking_ids.filtered(
            lambda p: p.picking_type_id.code == "outgoing" and p.x_zalo_return_requested
        )
        if return_pickings:
            return_pickings.write({
                "x_zalo_refund_id": refund_id,
                "x_zalo_refund_status": status,
                "x_zalo_refund_amount": amount_int if status in ("success", "pending") else 0.0,
                "x_zalo_refund_time": vals["x_zalo_refund_time"],
            })

        return res_json

    def action_query_zalo_refund_status(self):
        """
        Gọi Zalo Checkout SDK getRefundStatus API để tra cứu trạng thái hoàn tiền.
        Docs: https://docs.zaloplatforms.com/docs/MA/checkoutSdk/apis/getRefundStatus
        """
        self.ensure_one()
        order = self
        if not order.x_zalo_refund_id:
            raise UserError(_("Đơn hàng này chưa có Mã hoàn tiền Zalo (x_zalo_refund_id)."))

        app_id, private_key = order._get_zalo_checkout_credentials()
        if not app_id or not private_key:
            raise UserError(_("Chưa cấu hình Zalo App ID hoặc Private Key trong Odoo System Parameters."))

        raw_mac_str = f"appId={app_id}&refundId={order.x_zalo_refund_id}&privateKey={private_key}"
        mac = hmac.new(
            private_key.encode("utf-8"),
            raw_mac_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        params = {
            "appId": app_id,
            "refundId": order.x_zalo_refund_id,
            "mac": mac,
        }

        try:
            _logger.info("Gọi Zalo getRefundStatus cho đơn %s (refundId=%s)...", order.name, order.x_zalo_refund_id)
            resp = requests.get("https://payment-mini.zalo.me/api/refund", params=params, timeout=10)
            _logger.info("Kết quả Zalo getRefundStatus đơn %s: HTTP %s - Body: %s", order.name, resp.status_code, resp.text)
        except Exception as req_err:
            _logger.exception("Lỗi kết nối Zalo getRefundStatus cho đơn %s: %s", order.name, str(req_err))
            raise UserError(_("Lỗi kết nối tới Zalo Refund API: %s") % str(req_err))

        res_json = {}
        if resp.text and resp.text.strip():
            try:
                res_json = resp.json()
            except Exception as json_err:
                _logger.warning("Không thể parse JSON từ Zalo getRefundStatus response: %s (Lỗi: %s)", resp.text, str(json_err))

        return_code = res_json.get("returnCode")
        return_message = res_json.get("returnMessage", "")

        if return_code == 1:
            status = "success"
        elif return_code < 1:
            status = "failed"
        else:
            status = order.x_zalo_refund_status or "pending"

        vals = {
            "x_zalo_refund_log": (
                (order.x_zalo_refund_log or "")
                + f"\n[getRefundStatus] HTTP={resp.status_code}, returnCode={return_code}, "
                f"returnMessage={return_message}, status={status}, raw={resp.text}"
            )
        }
        if status == "success":
            vals["x_zalo_refund_status"] = "success"
            vals["x_zalo_refund_time"] = fields.Datetime.now()
        elif status == "failed" and order.x_zalo_refund_status == "pending":
            vals["x_zalo_refund_status"] = "failed"

        if vals:
            order.write(vals)
            return_pickings = order.picking_ids.filtered(
                lambda p: p.picking_type_id.code == "outgoing" and p.x_zalo_return_requested
            )
            if return_pickings:
                return_pickings.write({
                    "x_zalo_refund_status": vals.get("x_zalo_refund_status", order.x_zalo_refund_status),
                    "x_zalo_refund_time": vals.get("x_zalo_refund_time", order.x_zalo_refund_time),
                })

        return res_json

    @api.model
    def cron_sync_pending_zalo_refunds(self):
        """
        Cronjob tự động chạy ngầm trong Odoo (15 phút/lần).
        Tự động tìm các đơn hàng Zalo có x_zalo_refund_status = 'pending'
        và gọi getRefundStatus sang Zalo SDK Server để đồng bộ trạng thái.
        """
        pending_orders = self.search(
            [
                ("x_zalo_refund_status", "=", "pending"),
                ("x_zalo_refund_id", "!=", False),
                ("x_zalo_refund_id", "!=", ""),
            ],
            limit=50,
        )
        _logger.info("Zalo Refund Sync Cronjob: Đang quét %s đơn hàng đang hoàn tiền...", len(pending_orders))
        for order in pending_orders:
            try:
                order.action_query_zalo_refund_status()
            except Exception as e:
                _logger.warning("Zalo Refund Sync Cronjob lỗi ở đơn %s: %s", order.name, str(e))
        return True

