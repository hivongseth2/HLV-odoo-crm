import hashlib
import hmac
import json
import logging
import re
import time
import unicodedata
from markupsafe import Markup

from odoo import fields
from odoo.http import request, Response
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ZaloBaseAPI:
    """Base class chứa các helper dùng chung cho tất cả Zalo API controllers."""

    ALLOWED_IMAGE_MODELS = {
        "product.product",
        "product.template",
        "pos.category",
        "zalo.miniapp.banner",
        "product.multi.image",
    }

    @staticmethod
    def _normalize_vn_phone(phone):
        if not phone:
            return ""
        digits = re.sub(r"\D", "", str(phone))
        if len(digits) == 11 and digits.startswith("84"):
            digits = "0" + digits[2:]
        elif len(digits) == 12 and digits.startswith("084"):
            digits = "0" + digits[3:]
        return digits

    # ── Dia chi Viet Nam ────────────────────────────────────────────────

    #: Tien to hanh chinh can bo truoc khi doi chieu voi res.country.state.
    #: Odoo luu ten tinh tran ("Tuyen Quang") con picker cua Mini App tra ve
    #: kem tien to ("Tinh Tuyen Quang").
    VN_PROVINCE_PREFIXES = (
        "tinh ", "thanh pho ", "tp. ", "tp ", "tt ",
    )

    #: Cac field tao nen mot dia chi hoan chinh. Dung khi dong bo dia chi giua
    #: cac partner - phai ghi TAT CA, ke ca gia tri rong, neu khong du lieu cu
    #: cua tinh khac se o lai va tron voi dia chi moi.
    ADDRESS_FIELDS = ("street", "street2", "city", "zip", "state_id", "country_id")

    @staticmethod
    def _strip_accents(value):
        return "".join(
            ch for ch in unicodedata.normalize("NFD", value or "")
            if unicodedata.category(ch) != "Mn"
        )

    @classmethod
    def _vn_country(cls):
        return request.env["res.country"].sudo().search([("code", "=", "VN")], limit=1)

    @classmethod
    def _vn_state_from_name(cls, name):
        """Doi ten tinh/thanh sang ban ghi res.country.state cua Viet Nam.

        Mini App lay danh sach tinh tu provinces.open-api.vn nen chi co TEN,
        khong co id cua Odoo. Khong map thi dia chi tao ra se trong state_id /
        country_id.

        Tra ve recordset rong neu khong khop - de nguyen con hon gan bua.
        """
        if not name:
            return request.env["res.country.state"].sudo().browse()

        country = cls._vn_country()
        State = request.env["res.country.state"].sudo()
        if not country:
            return State.browse()

        cleaned = (name or "").strip()
        plain = cls._strip_accents(cleaned).lower()
        for prefix in cls.VN_PROVINCE_PREFIXES:
            if plain.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
                break

        domain = [("country_id", "=", country.id)]
        state = State.search(domain + [("name", "=", cleaned)], limit=1)
        if state:
            return state
        return State.search(domain + [("name", "ilike", cleaned)], limit=1)

    @classmethod
    def _resolve_address_location(cls, body, fallback_name=""):
        """Suy ra state_id / country_id cho mot dia chi.

        Uu tien id do client gui len; neu khong co thi map theo ten tinh
        (`province_name`, sau do den `fallback_name` - thuong la `city`).
        Tra ve dict rong khi khong xac dinh duoc de caller khong ghi de.
        """
        vals = {}

        state_id = body.get("state_id")
        if state_id:
            state = request.env["res.country.state"].sudo().browse(state_id)
            state = state if state.exists() else None
        else:
            state = cls._vn_state_from_name(body.get("province_name") or fallback_name)

        if state:
            vals["state_id"] = state.id
            vals["country_id"] = state.country_id.id
            return vals

        country_id = body.get("country_id")
        if country_id:
            country = request.env["res.country"].sudo().browse(country_id)
            if country.exists():
                vals["country_id"] = country.id
        return vals

    @staticmethod
    def _get_secret_key():
        Param = request.env["ir.config_parameter"].sudo()
        key = Param.get_param("zalo_api_secret", "") or Param.get_param("hlv_loyalty.zalo_secret_key", "") or Param.get_param("zalo.secret_key", "")
        key = str(key or "").strip()
        if not key:
            raise UserError("Zalo API secret key not configured. Set 'zalo_api_secret' in System Parameters.")
        return key

    @staticmethod
    def _get_cors_origin():
        """Return CORS origin từ config parameter, fallback về '*'."""
        try:
            origin = request.env["ir.config_parameter"].sudo().get_param(
                "zalo_api_cors_origin", "*"
            )
            return origin
        except Exception:
            return "*"

    @staticmethod
    def _cors_headers():
        """Return CORS headers dict với origin configurable.
        Tránh trùng lặp Access-Control-Allow-Origin nếu route đã có cors='*'."""
        headers = {
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
            "Access-Control-Max-Age": "86400",
        }
        has_route_cors = False
        try:
            if hasattr(request, "endpoint") and request.endpoint and hasattr(request.endpoint, "routing"):
                has_route_cors = bool(request.endpoint.routing.get("cors"))
        except Exception:
            pass

        if not has_route_cors:
            headers["Access-Control-Allow-Origin"] = ZaloBaseAPI._get_cors_origin()
        return headers

    @staticmethod
    def _response_options():
        """Response 200 OK cho HTTP OPTIONS preflight request."""
        headers = ZaloBaseAPI._cors_headers()
        return Response(status=200, headers=headers)

    def _check_options(self):
        """Trả về 200 OK Response nếu request là OPTIONS preflight."""
        if request.httprequest.method == "OPTIONS":
            return self._response_options()
        return None

    @staticmethod
    def _response_success(data=None, status=200):
        payload = {"success": True, "data": data or {}}
        headers = ZaloBaseAPI._cors_headers()
        return Response(
            json.dumps(payload, default=str),
            status=status,
            content_type="application/json",
            headers=headers,
        )

    @staticmethod
    def _response_success_cached(data=None, max_age=300, status=200):
        """Response thành công với Cache-Control header (mặc định 5 phút)."""
        payload = {"success": True, "data": data or {}}
        headers = ZaloBaseAPI._cors_headers()
        headers["Cache-Control"] = f"public, max-age={max_age}"
        return Response(
            json.dumps(payload, default=str),
            status=status,
            content_type="application/json",
            headers=headers,
        )

    @staticmethod
    def _response_error(code, message, status=400):
        payload = {
            "success": False,
            "error": {"code": code, "message": message},
        }
        headers = ZaloBaseAPI._cors_headers()
        return Response(
            json.dumps(payload, default=str),
            status=status,
            content_type="application/json",
            headers=headers,
        )

    # =========================================================================
    # Loyalty portal account helper
    # =========================================================================

    @classmethod
    def _get_scoped_portal_account(cls, partner, phone=None):
        """Tim chinh xac tai khoan loyalty portal cua partner theo so dien thoai."""
        if not partner or "hlv.loyalty.portal.account" not in request.env:
            return None
        Account = request.env["hlv.loyalty.portal.account"].sudo()
        root = partner._get_loyalty_root() if hasattr(partner, "_get_loyalty_root") else partner
        family_ids = root._get_loyalty_family_partner_ids() if hasattr(root, "_get_loyalty_family_partner_ids") else [root.id, partner.id]

        normalized = cls._normalize_vn_phone(phone) if phone else ""
        if normalized:
            acc = Account.search([
                ("partner_id", "in", family_ids),
                ("portal_phone", "=", normalized),
                ("active", "=", True),
            ], limit=1)
            if acc:
                return acc
        # Fallback to default or first account of partner
        if hasattr(root, "loyalty_portal_account_ids") and root.loyalty_portal_account_ids:
            return root.loyalty_portal_account_ids.filtered(lambda a: a.is_default)[:1] or root.loyalty_portal_account_ids.filtered(lambda a: a.active)[:1]
        return None

    @staticmethod
    def _parse_int(value, default=0):
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _parse_float(value, default=0.0):
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _get_record_timestamp(record):
        if not record or not record.exists():
            return None
        try:
            from odoo import fields
            wdate = getattr(record, "write_date", None) or getattr(record, "create_date", None)
            if wdate:
                return int(fields.Datetime.to_datetime(wdate).timestamp())
        except Exception:
            pass
        return None

    @staticmethod
    def _get_image_url(model, rec_id, field="image_128", write_date=None):
        """Return a relative URL for the image with versioning.
        Uses safe model name (dots replaced with dashes) for GET endpoint.
        Frontend can use this URL directly in <img> tags.
        Example: /api/v1/zalo/image/product-product/123/image_128?v=1722749821"""
        if not rec_id:
            return None
        safe_model = model.replace(".", "-")
        url = f"/api/v1/zalo/image/{safe_model}/{rec_id}/{field}"
        if write_date:
            try:
                from odoo import fields
                if isinstance(write_date, (int, float)):
                    ts = int(write_date)
                else:
                    ts = int(fields.Datetime.to_datetime(write_date).timestamp())
                url += f"?v={ts}"
            except Exception:
                pass
        return url


    @staticmethod
    def _request_json():
        raw = request.httprequest.data or b"{}"
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            _logger.warning("Failed to parse request JSON: %s", e)
            return {}

    @staticmethod
    def _parse_limit_offset(body, default_limit=20, max_limit=100):
        """Parse và validate limit/offset từ request body.
        Trả về (limit, offset) hoặc raise ValueError nếu offset âm."""
        limit = ZaloBaseAPI._parse_int(body.get("limit"), default_limit)
        offset = ZaloBaseAPI._parse_int(body.get("offset"), 0)
        if offset < 0:
            raise ValueError("offset không được âm")
        limit = min(max(limit, 1), max_limit)
        return limit, offset

    # =========================================================================
    # Auth & Ownership Verification
    # =========================================================================

    def _auth_required(self):
        """Return partner_id từ token, hoặc Response lỗi."""
        auth_header = request.httprequest.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return self._response_error("AUTH_REQUIRED", "Thiếu token xác thực", 401)
        token = auth_header[7:].strip()
        pid = self._verify_token(token)
        if not pid:
            return self._response_error("INVALID_TOKEN", "Token không hợp lệ hoặc đã hết hạn", 401)
        return pid

    def _auth_and_verify_owner(self, contact_id):
        """Auth + kiểm tra contact_id khớp với token owner.
        Trả về partner_id nếu hợp lệ, hoặc Response lỗi nếu không."""
        result = self._auth_required()
        if isinstance(result, Response):
            return result
        if result != contact_id:
            _logger.warning(
                "Ownership mismatch: token owner=%s, requested contact_id=%s",
                result, contact_id,
            )
            return self._response_error("FORBIDDEN", "Không có quyền truy cập", 403)
        return result

    @staticmethod
    def _token_signature(secret, payload):
        return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def _parse_token(self, token):
        """Giải mã token, trả `(partner_id, account_id)` hoặc None nếu không hợp lệ.

        ĐÂY LÀ BẢN DUY NHẤT. Trước kia `ZaloContactAPI` có một bản override y
        hệt, và việc sửa một bản mà quên bản kia đã khiến token qua được nhóm
        endpoint này nhưng bị chặn ở nhóm kia — khách đang dùng thì bị đá ra
        giữa chừng. Đừng tạo lại bản sao.

        Ba định dạng được chấp nhận:
          partner_id.account_id.timestamp.chữ_ký  — bản hiện tại
          partner_id.timestamp.chữ_ký             — bản trước, chưa mang account
          (cùng 3 phần, chữ ký tính kèm SĐT)      — bản cũ nhất

        `account_id` cho biết khách đăng nhập vào TÀI KHOẢN PORTAL nào. Một
        công ty có nhiều người thu mua, mỗi người một tài khoản điểm và một
        lịch sử đơn riêng; không có thông tin này thì server buộc phải đoán
        theo số điện thoại do client gửi lên — vừa sai vừa không tin được.

        Payload CỐ TÌNH không chứa số điện thoại: token ký bằng SĐT lấy từ
        Zalo, còn chỗ kiểm lại lấy `res.partner.phone` — hai số này khác nhau
        với khách doanh nghiệp nên chữ ký luôn lệch.
        """
        try:
            parts = token.split(".")
            secret = self._get_secret_key()

            if len(parts) == 4:
                partner_id = int(parts[0])
                account_id = int(parts[1]) or None
                timestamp = int(parts[2])
                signature = parts[3]
                payload = f"{partner_id}:{parts[1]}:{timestamp}"
            elif len(parts) == 3:
                partner_id = int(parts[0])
                account_id = None
                timestamp = int(parts[1])
                signature = parts[2]
                payload = f"{partner_id}:{timestamp}"
            else:
                return None

            partner = request.env["res.partner"].sudo().browse(partner_id)
            if not partner.exists():
                return None

            if not hmac.compare_digest(signature, self._token_signature(secret, payload)):
                # Token cũ nhất còn nhét SĐT vào payload. Vẫn chấp nhận để
                # người đang đăng nhập không bị văng ra; sau 30 ngày tự hết hạn.
                if len(parts) != 3:
                    return None
                legacy_phone = self._normalize_vn_phone(
                    partner.phone or partner.mobile or ""
                )
                legacy_sig = self._token_signature(
                    secret, f"{partner_id}:{legacy_phone}:{timestamp}"
                )
                if not hmac.compare_digest(signature, legacy_sig):
                    return None

            # Kiểm tra hết hạn: 30 ngày
            if time.time() - timestamp > 30 * 24 * 3600:
                return None

            return partner_id, account_id
        except (ValueError, IndexError, Exception):
            return None

    def _verify_token(self, token):
        """Chỉ trả partner_id — giữ nguyên chữ ký hàm cho các nơi đang gọi."""
        parsed = self._parse_token(token)
        return parsed[0] if parsed else None

    def _auth_account_id(self):
        """Tài khoản Portal gắn với token đang gửi lên.

        Trả None với token cũ (chưa mang account_id). Nơi gọi phải tự quyết
        định: với dữ liệu riêng theo từng người thu mua thì coi như không có
        quyền xem, đừng lùi về phạm vi cả công ty.
        """
        auth_header = request.httprequest.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None
        parsed = self._parse_token(auth_header[7:].strip())
        return parsed[1] if parsed else None

    # =========================================================================
    # Logging helper
    # =========================================================================

    def _log_request(self, method, path, partner_id=None, status=200, elapsed_ms=0):
        """Ghi log cấu trúc cho mỗi API call."""
        _logger.info(
            "ZALO_API %s %s partner=%s status=%s time=%.2fms",
            method, path, partner_id or "anonymous", status, elapsed_ms,
        )

    # =========================================================================
    # Order Notification Helpers
    # =========================================================================

    def _notify_order_to_discuss_channel(self, sale_order, payment_method="", customer_note=""):
        """Gửi tin nhắn thông báo đơn hàng mới từ Zalo Mini App:
        1. Gửi tin nhắn Chat trực tiếp 1-1 (Direct Message) giữa tài khoản hệ thống (OdooBot) và các tài khoản được cấu hình -> Làm nhảy popup Chat box nổi ngay trên màn hình người nhận!
        2. Gửi tin nhắn vào Kênh Thảo luận (Discuss Channel) nếu có cấu hình.
        """
        try:
            ICP = request.env["ir.config_parameter"].sudo()
            base_url = ICP.get_param("web.base.url", "")
            order_url = f"{base_url}/web#id={sale_order.id}&model=sale.order&view_type=form" if base_url else ""

            order_link_html = f"<a href='{order_url}'><b>{sale_order.name}</b></a>" if order_url else f"<b>{sale_order.name}</b>"
            amount_formatted = f"{sale_order.amount_total:,.0f} ₫"
            partner = sale_order.partner_id
            phone_str = partner.phone or partner.mobile or "N/A"

            msg_body = Markup(
                "🛒 <b>CÓ ĐƠN HÀNG MỚI TỪ ZALO MINI APP!</b><br/>"
                "• <b>Mã đơn:</b> %s<br/>"
                "• <b>Khách hàng:</b> %s (SĐT: %s)<br/>"
                "• <b>Tổng tiền:</b> <span style='color: #1177b7; font-weight: bold;'>%s</span><br/>"
                "• <b>Phương thức thanh toán:</b> %s"
            ) % (
                Markup(order_link_html),
                partner.name,
                phone_str,
                amount_formatted,
                payment_method.upper() if payment_method else "N/A",
            )
            if customer_note:
                msg_body += Markup("<br/>• <b>Ghi chú:</b> %s") % customer_note

            # Lấy đối tượng gửi tin (tài khoản được cấu hình trong Cài đặt hoặc mặc định là OdooBot)
            raw_sender_id = ICP.get_param("hlv_zalo_miniapp.order_sender_user_id", "")
            bot_partner = None
            if raw_sender_id and str(raw_sender_id).isdigit():
                sender_user = request.env["res.users"].sudo().browse(int(raw_sender_id))
                if sender_user.exists() and sender_user.partner_id:
                    bot_partner = sender_user.partner_id

            if not bot_partner:
                bot_partner = request.env.ref("base.partner_root", raise_if_not_found=False)
            if not bot_partner:
                bot_user = request.env.ref("base.user_root", raise_if_not_found=False) or request.env.user
                bot_partner = bot_user.partner_id

            DiscussChannel = request.env["discuss.channel"].sudo()

            # ===== 1. GỬI DIRECT CHAT (CHAT 1-1 TRỰC TIẾP TÀI KHOẢN VỚI TÀI KHOẢN) =====
            # Tin nhắn Direct Chat giữa tài khoản sẽ làm nhảy popup Chat box nổi ngay trên màn hình người nhận
            raw_order_user_ids = ICP.get_param("hlv_zalo_miniapp.order_notify_user_ids", "")
            target_user_ids = []
            if raw_order_user_ids:
                try:
                    clean_ids = raw_order_user_ids.replace("[", "").replace("]", "").split(",")
                    target_user_ids = [int(u.strip()) for u in clean_ids if u.strip().isdigit()]
                except Exception:
                    pass

            target_users = request.env["res.users"].sudo().browse(target_user_ids).filtered(lambda u: u.active)
            if not target_users and sale_order.user_id and sale_order.user_id.active:
                target_users = sale_order.user_id

            for user in target_users:
                target_partner = user.partner_id
                if not target_partner.exists() or target_partner.id == bot_partner.id:
                    continue
                try:
                    # Tìm hoặc tạo kênh chat 1-1 giữa bot/hệ thống và tài khoản nhân viên
                    direct_channel = DiscussChannel.search([
                        ("channel_type", "=", "chat"),
                        ("channel_member_ids.partner_id", "in", [bot_partner.id]),
                        ("channel_member_ids.partner_id", "in", [target_partner.id]),
                    ], limit=1)

                    if not direct_channel:
                        try:
                            direct_channel = DiscussChannel.with_user(request.env.ref("base.user_root", raise_if_not_found=False) or 1).channel_get(partners_to=[target_partner.id])
                        except Exception:
                            direct_channel = None

                    if not direct_channel:
                        direct_channel = DiscussChannel.create({
                            "name": f"{bot_partner.name}, {target_partner.name}",
                            "channel_type": "chat",
                            "channel_member_ids": [
                                (0, 0, {"partner_id": bot_partner.id}),
                                (0, 0, {"partner_id": target_partner.id}),
                            ],
                        })

                    if direct_channel:
                        direct_channel.message_post(
                            body=msg_body,
                            message_type="comment",
                            subtype_xmlid="mail.mt_comment",
                            author_id=bot_partner.id,
                        )
                        _logger.info("Direct Chat popup message sent to user %s (partner %s)", user.name, target_partner.name)
                except Exception as de:
                    _logger.warning("Failed to send direct chat message to user %s: %s", user.name, de)

            # ===== 2. GỬI KÊNH THẢO LUẬN (DISCUSS CHANNEL) NẾU CÓ CẤU HÌNH =====
            channel_id_raw = ICP.get_param("hlv_zalo_miniapp.order_notify_channel_id", "")
            if channel_id_raw and str(channel_id_raw).isdigit():
                group_channel = DiscussChannel.browse(int(channel_id_raw))
                if group_channel.exists():
                    group_channel.message_post(
                        body=msg_body,
                        message_type="comment",
                        subtype_xmlid="mail.mt_comment",
                    )
        except Exception as e:
            _logger.warning("Failed to notify order via chat: %s", e)

    def _send_order_zns_notification(self, sale_order):
        """Gửi ZNS thông báo xác nhận đơn hàng tới SĐT khách qua module hlv_zalo_zns (nếu có config)."""
        try:
            if "hlv.zalo.zns" not in request.env:
                return

            zns_config = request.env["hlv.zalo.zns"].sudo().search([], limit=1)
            if not zns_config:
                return

            template_id = getattr(zns_config, "wp_template_id", False) or getattr(zns_config, "template_id", False)
            if not template_id:
                return

            phone = sale_order.partner_id.phone or sale_order.partner_id.mobile
            if not phone:
                return

            params = {
                "order_code": sale_order.name,
                "customer_name": sale_order.partner_id.name,
                "cost": str(int(round(sale_order.amount_total))),
                "date": fields.Date.to_string(sale_order.date_order.date() if sale_order.date_order else fields.Date.today()),
            }

            zns_config.send_zns(phone, params, template_id_override=template_id)
            _logger.info("ZNS order confirmation sent for %s to %s", sale_order.name, phone)
        except Exception as e:
            _logger.warning("Failed to send ZNS order confirmation: %s", e)

    def _send_order_zalo_notification_message(self, sale_order, payment_method="", customer_note=""):
        """Gửi tin nhắn Zalo trực tiếp về điện thoại cho các Zalo User ID (Admin/Quản lý) qua hlv.zalo.stock.notification."""
        try:
            Param = request.env["ir.config_parameter"].sudo()
            raw_zalo_uids = Param.get_param("hlv_zalo_miniapp.return_zalo_uids", "")
            zalo_recipients = [u.strip() for u in raw_zalo_uids.split(",") if u.strip()]

            if not zalo_recipients or "hlv.zalo.stock.notification" not in request.env:
                return

            zalo_config = request.env["hlv.zalo.stock.notification"].sudo()._get_active_config()
            if not zalo_config:
                return

            base_url = Param.get_param("web.base.url", "")
            order_url = f"{base_url}/web#id={sale_order.id}&model=sale.order&view_type=form" if base_url else ""
            partner = sale_order.partner_id
            phone_str = partner.phone or partner.mobile or "N/A"

            zalo_msg = (
                f"🔔 CÓ ĐƠN HÀNG MỚI TỪ ZALO MINI APP\n"
                f"  • Mã đơn: {sale_order.name}\n"
                f"  • Khách hàng: {partner.name} ({phone_str})\n"
                f"  • Tổng tiền: {sale_order.amount_total:,.0f} đ\n"
                f"  • PTTT: {payment_method.upper() if payment_method else 'N/A'}\n"
            )
            if customer_note:
                zalo_msg += f"  • Ghi chú: {customer_note}\n"
            if order_url:
                zalo_msg += f"👉 Mở xem trên Odoo: {order_url}"

            for uid in zalo_recipients:
                try:
                    zalo_config.send_notification_message(uid, zalo_msg)
                    _logger.info("✓ Zalo Order Notification sent to UID %s for order %s", uid, sale_order.name)
                except Exception as ze:
                    _logger.error("✗ Lỗi gửi Zalo Order Notification tới %s: %s", uid, ze)
        except Exception as ex:
            _logger.warning("Lỗi gửi Zalo Order Notification cho đơn %s: %s", sale_order.name, ex)

    # =========================================================================
    # Loyalty Voucher Verification Helper
    # =========================================================================

    @staticmethod
    def _verify_voucher_code(code, partner_id, order_amount=0):
        """Xác thực mã voucher cho partner, kiểm tra quyền sở hữu gia đình, hạn dùng, giá trị đơn tối thiểu."""
        try:
            if not code:
                return {"valid": False, "error": "Mã voucher trống"}
            if "hlv.loyalty.voucher" not in request.env:
                return {"valid": False, "error": "Hệ thống Loyalty chưa được kích hoạt"}

            Voucher = request.env["hlv.loyalty.voucher"].sudo()
            voucher = Voucher.search([("code", "=", str(code).strip().upper())], limit=1)
            if not voucher:
                return {"valid": False, "error": "Mã voucher không tồn tại"}
            if voucher.state != "active":
                return {"valid": False, "error": "Voucher không còn hiệu lực"}

            partner = request.env["res.partner"].sudo().browse(int(partner_id))
            root = partner._get_loyalty_root() if hasattr(partner, "_get_loyalty_root") else partner
            family_ids = root._get_loyalty_family_partner_ids() if hasattr(root, "_get_loyalty_family_partner_ids") else [root.id, partner.id]

            if voucher.partner_id.id not in family_ids:
                return {"valid": False, "error": "Voucher không thuộc về bạn"}

            if voucher.date_expiry:
                now = fields.Datetime.now()
                if voucher.date_expiry < now:
                    return {"valid": False, "error": "Voucher đã hết hạn"}

            min_amount = getattr(voucher, "min_order_amount", 0) or 0
            if order_amount < min_amount:
                return {"valid": False, "error": f"Đơn hàng tối thiểu {min_amount:,.0f}₫"}

            reward_type = getattr(voucher, "reward_type", "discount") or "discount"
            discount_type = getattr(voucher, "discount_type", "fixed") or "fixed"
            raw_discount_value = getattr(voucher, "discount_value", 0) or 0
            max_discount = getattr(voucher, "max_discount_amount", 0) or 0

            discount_value = 0
            if reward_type == "free_shipping":
                discount_value = 0
            elif discount_type == "percent":
                discount_value = order_amount * raw_discount_value / 100
                if max_discount > 0:
                    discount_value = min(discount_value, max_discount)
            else:
                discount_value = min(raw_discount_value, order_amount)

            return {
                "valid": True,
                "voucher_id": voucher.id,
                "voucher_code": voucher.code,
                "reward_type": reward_type,
                "discount_type": discount_type,
                "discount_value": raw_discount_value,
                "estimated_discount": discount_value,
            }
        except Exception as e:
            _logger.warning("Voucher verification error: %s", e)
            return {"valid": False, "error": "Không thể kiểm tra voucher"}
