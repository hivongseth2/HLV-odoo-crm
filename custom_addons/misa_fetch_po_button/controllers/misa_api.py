# controllers/misa_api.py
# -*- coding: utf-8 -*-
import logging, json,re
from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)

class MisaApiSaleOrder(http.Controller):

    @http.route('/api/misa/sale_order/edit_lock', type='json', auth='none', methods=['POST', 'OPTIONS'], csrf=False, cors="*")
    def api_misa_sale_order_edit_lock(self, **payload):
        """Nhận MISA order ID và khóa riêng việc xác nhận phiếu OUT của SO."""
        if not payload:
            body = request.httprequest.get_json(force=False, silent=True) or {}
            payload = dict(body.get('params') or body)

        raw_token = payload.get('token') or request.httprequest.headers.get('X-MISA-Token')
        token = re.sub(r'[\u200B-\u200D\uFEFF]', '', (raw_token or '').strip())
        expected = request.env['ir.config_parameter'].sudo().get_param('misa.api.token') or 'hoanglongvu'
        expected = re.sub(r'[\u200B-\u200D\uFEFF]', '', expected)
        if token != expected:
            return {"ok": False, "error": "invalid_token", "message": "Token không hợp lệ."}

        misa_order_id = str(payload.get('misa_order_id') or payload.get('id') or '').strip()
        if not misa_order_id:
            return {"ok": False, "error": "missing_misa_order_id", "message": "Thiếu MISA order ID."}

        admin_user = request.env.ref('base.user_admin', raise_if_not_found=False)
        if not admin_user:
            return {"ok": False, "error": "admin_not_found", "message": "Không tìm thấy tài khoản quản trị."}

        try:
            order = request.env(user=admin_user)['sale.order'].sudo().search([
                ('misa_id', '=', misa_order_id),
                ('state', '!=', 'cancel'),
            ], limit=1)
            if not order:
                return {
                    "ok": False,
                    "error": "not_found",
                    "message": "Không tìm thấy đơn Odoo theo MISA ID %s." % misa_order_id,
                }

            # Khóa OUT và tạo queue trong cùng transaction. Queue chưa trigger
            # ngay để request /resync kế tiếp của extension tái sử dụng rồi đánh
            # thức cron. Nếu sale reload làm mất callback, cron phút vẫn xử lý
            # queue này; không còn trạng thái khóa thành công nhưng chưa gửi yêu
            # cầu thay đổi.
            with request.env.cr.savepoint():
                lock_started = not order.misa_sale_edit_locked
                order.with_context(
                    misa_defer_sale_edit_notification=True,
                ).action_misa_start_sale_edit()
                enqueue_result = request.env(user=admin_user)[
                    'misa.sync.queue'
                ].sudo().enqueue_sale_order(
                    misa_order_id=misa_order_id,
                    payload={
                        'misa_order_id': misa_order_id,
                        'create_when_missing': False,
                        'source': 'sale_edit_lock',
                        'notify_sale_edit_lock': lock_started,
                    },
                    trigger_processor=False,
                )
                queue = enqueue_result['queue']

            return {
                "ok": True,
                "order_id": order.id,
                "name": order.name,
                "misa_order_id": order.misa_id,
                "misa_sale_edit_locked": True,
                "misa_sale_edit_locked_at": fields.Datetime.to_string(order.misa_sale_edit_locked_at),
                "queued": True,
                "queue_id": queue.id,
                "deduplicated": not enqueue_result["created"],
                "message": "Đã khóa xác nhận phiếu xuất kho; PICK/PACK vẫn xử lý bình thường.",
            }
        except Exception as error:
            _logger.exception("MISA API /edit_lock exception for %s: %s", misa_order_id, error)
            return {"ok": False, "error": "exception", "message": str(error)}

    @http.route('/api/misa/sale_order/resync', type='json', auth='none', methods=['POST', 'OPTIONS'], csrf=False, cors="*")
    def api_misa_sale_order_resync(self, **payload):
        """
        Public API: không yêu cầu login.
        Body JSON ví dụ:
        {
          "token": "hoanglongvu",
          "misa_order_id": "abc-123",
          "warehouse_id": 1,
          "create_when_missing": true
        }
        """

        # ---- Lấy JSON body an toàn (nếu Postman gửi sai Content-Type vẫn bắt được) ----
        try:
            # Với type='json', Odoo sẽ parse vào **payload; nếu rỗng thì tự đọc lại từ raw.
            if not payload:
                try:
                    body = request.httprequest.get_json(force=False, silent=True)
                except Exception:
                    body = None
                if body is None:
                    raw = (request.httprequest.data or b'').decode('utf-8', errors='ignore')
                    try:
                        body = json.loads(raw) if raw else {}
                    except Exception:
                        body = {}
                payload = dict(body or {})
        except Exception:
            # Không chặn flow vì chỉ là logging/phòng thủ
            pass

        # ---- Lấy token từ body hoặc header ----
        raw_token = (payload.get("token") if isinstance(payload, dict) else None) \
                    or request.httprequest.headers.get('X-MISA-Token')
        token = (raw_token or "").strip()

        # Log nhẹ xem server nhận gì (không dùng request.jsonrequest nữa)
        # _logger.info("MISA API /resync payload=%r token=%r", payload, token)

        # ---- Token check (có thể thay bằng system parameter nếu bạn muốn) ----
        expected = request.env['ir.config_parameter'].sudo().get_param('misa.api.token') or "hoanglongvu"

        # loại zero-width nếu có
        try:
            import re
            token = re.sub(r'[\u200B-\u200D\uFEFF]', '', token)
            expected = re.sub(r'[\u200B-\u200D\uFEFF]', '', expected)
        except Exception:
            pass

        if token != expected:
            return {"ok": False, "error": "invalid_token", "message": "Token không hợp lệ."}

        # ---- Lấy tham số nghiệp vụ ----
        misa_order_id = payload.get("misa_order_id")
        warehouse_id = payload.get("warehouse_id")
        create_when_missing = payload.get("create_when_missing", True)
        misa_order_id = str(misa_order_id or "").strip()
        if not misa_order_id:
            return {
                "ok": False,
                "error": "missing_misa_order_id",
                "message": "Thiếu MISA order ID.",
            }

        # ---- Chạy dưới quyền admin ----
        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        if not admin_user:
            return {"ok": False, "error": "admin_not_found"}

        try:
            # env_admin = request.env(user=admin_user).sudo()
            env_admin = request.env(user=admin_user)

            # Thay vì gọi đồng bộ, đưa vào hàng chờ
            enqueue_result = env_admin["misa.sync.queue"].sudo().enqueue_sale_order(
                misa_order_id=misa_order_id,
                payload=payload,
            )
            queue = enqueue_result["queue"]
            return {
                "ok": True,
                "queued": True,
                "queue_id": queue.id,
                "deduplicated": not enqueue_result["created"],
                "triggered": enqueue_result["triggered"],
                "message": "Đã đưa Đơn bán hàng vào hàng chờ đồng bộ.",
            }
        except Exception as e:
            _logger.exception("MISA API /resync exception: %s", e)
            return {"ok": False, "error": "exception", "message": str(e)}


    @http.route('/api/misa/sale_order/resync_by_name', type='json', auth='none', methods=['POST', 'OPTIONS'], csrf=False, cors="*")
    def api_misa_sale_order_resync_by_name(self, **payload):
        # ---- parse body y như bạn đang làm ở trên ----
        try:
            if not payload:
                try:
                    body = request.httprequest.get_json(force=False, silent=True)
                except Exception:
                    body = None
                if body is None:
                    raw = (request.httprequest.data or b'').decode('utf-8', errors='ignore')
                    try:
                        body = json.loads(raw) if raw else {}
                    except Exception:
                        body = {}
                payload = dict(body or {})
        except Exception:
            pass

        # ---- Token ----
        raw_token = (payload.get("token") if isinstance(payload, dict) else None) \
                    or request.httprequest.headers.get('X-MISA-Token')
        token = (raw_token or "").strip()
        expected = request.env['ir.config_parameter'].sudo().get_param('misa.api.token') or "hoanglongvu"
        token = re.sub(r'[\u200B-\u200D\uFEFF]', '', token)
        expected = re.sub(r'[\u200B-\u200D\uFEFF]', '', expected)
        if token != expected:
            return {"ok": False, "error": "invalid_token", "message": "Token không hợp lệ."}

        name = (payload.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "missing_name", "message": "Thiếu tham số name"}

        # ---- Switch sang user admin (KHÔNG .sudo() trên Environment) ----
        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        if not admin_user:
            return {"ok": False, "error": "admin_not_found"}

        env_admin = request.env(user=admin_user)  # <-- KHÔNG .sudo() ở đây

        # Tìm SO theo name, cho phép sudo trên recordset nếu cần
        SaleOrder = env_admin["sale.order"].sudo()  # <-- sudo trên model/recordset
        order = SaleOrder.search([("name", "=", name)], limit=1)
        if not order:
            return {"ok": False, "error": "not_found", "message": f"Không tìm thấy sale.order có name={name}"}

        # Field đúng là misa_id (không phải misa_order_id)
        misa_order_id = getattr(order, "misa_id", False)
        if not misa_order_id:
            return {"ok": False, "error": "no_misa_id", "message": f"Đơn {name} chưa có misa_id"}

        warehouse_id = payload.get("warehouse_id")
        create_when_missing = payload.get("create_when_missing", True)

        try:
            # Gọi API model chuẩn
            result = env_admin["sale.order"].api_resync_by_misa(
                misa_order_id=misa_order_id,
                warehouse_id=warehouse_id,
                create_when_missing=bool(create_when_missing),
            )
            # Bổ sung thông tin tra cứu
            result["name_lookup"] = name
            result["misa_order_id"] = misa_order_id
            return result
        except Exception as e:
            _logger.exception("MISA API /resync_by_name exception: %s", e)
            return {"ok": False, "error": "exception", "message": str(e)}
        
        
        
    @http.route('/api/misa/sale_order/cancel_by_name', type='json', auth='none', methods=['POST', 'OPTIONS'], csrf=False, cors="*")
    def api_misa_sale_order_cancel_by_name(self, **payload):
        """
        API Cancel SO theo Name (ví dụ: SO00123).
        Body JSON:
        {
          "token": "...",
          "name": "SO00123"
        }
        """
        # ==================================================================================
        # 1. PARSE BODY (Copy logic chuẩn từ các hàm trên để đảm bảo an toàn với Postman)
        # ==================================================================================
        try:
            if not payload:
                try:
                    body = request.httprequest.get_json(force=False, silent=True)
                except Exception:
                    body = None
                if body is None:
                    raw = (request.httprequest.data or b'').decode('utf-8', errors='ignore')
                    try:
                        body = json.loads(raw) if raw else {}
                    except Exception:
                        body = {}
                payload = dict(body or {})
        except Exception:
            pass

        # ==================================================================================
        # 2. CHECK TOKEN
        # ==================================================================================
        raw_token = (payload.get("token") if isinstance(payload, dict) else None) \
                    or request.httprequest.headers.get('X-MISA-Token')
        token = (raw_token or "").strip()
        
        # Log request
        _logger.info("MISA API /cancel_by_name payload=%r token=%r", payload, token)

        expected = request.env['ir.config_parameter'].sudo().get_param('misa.api.token') or "hoanglongvu"
        
        # Clean hidden chars
        token = re.sub(r'[\u200B-\u200D\uFEFF]', '', token)
        expected = re.sub(r'[\u200B-\u200D\uFEFF]', '', expected)

        if token != expected:
            return {"ok": False, "error": "invalid_token", "message": "Token không hợp lệ."}

        # ==================================================================================
        # 3. LOGIC NGHIỆP VỤ (CANCEL)
        # ==================================================================================
        name = (payload.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "missing_name", "message": "Thiếu tham số name"}

        # Lấy user Admin
        admin_user = request.env.ref("base.user_admin", raise_if_not_found=False)
        if not admin_user:
            return {"ok": False, "error": "admin_not_found"}

        # Tạo môi trường admin
        env_admin = request.env(user=admin_user)
        
        try:
            SaleOrder = env_admin["sale.order"].sudo()
            order = SaleOrder.search([("name", "=", name)], limit=1)
            
            if not order:
                return {"ok": False, "error": "not_found", "message": f"Không tìm thấy đơn {name}"}

            if order.state == 'cancel':
                return {"ok": True, "status": "already_cancelled", "message": "Đơn đã huỷ rồi."}

            # ---------------------------------------------------------
            # BƯỚC 1: CHỈ CHẶN KHI PHIẾU OUT (OUTGOING) ĐÃ DONE
            # Pick/Pack done vẫn cho hủy — Odoo sẽ tự cascade hủy toàn bộ picking
            # ---------------------------------------------------------
            out_done = order.picking_ids.filtered(
                lambda p: p.picking_type_id.code == 'outgoing' and p.state == 'done'
            )
            if out_done:
                names = ', '.join(out_done.mapped('name'))
                return {
                    "ok": False,
                    "error": "out_picking_done",
                    "message": f"Lỗi: Đơn {name} đã xuất kho hoàn thành (phiếu OUT: {names}). Phải trả hàng về kho trước khi huỷ."
                }

            # ---------------------------------------------------------
            # BƯỚC 2: XỬ LÝ HOÁ ĐƠN (INVOICE)
            # ---------------------------------------------------------
            for invoice in order.invoice_ids:
                if invoice.state == 'posted':
                    return {
                        "ok": False,
                        "error": "invoice_posted",
                        "message": f"Lỗi: Đơn {name} đã vào sổ hoá đơn. Cần huỷ hoá đơn/làm Credit Note trước."
                    }

            # ---------------------------------------------------------
            # BƯỚC 3: HUỶ SO — Odoo tự cascade hủy pick/pack/out còn lại
            # ---------------------------------------------------------
            if order.state == 'done':
                order.action_unlock()

            order.with_context(disable_cancel_warning=True).action_cancel()

            # ---------------------------------------------------------
            # BƯỚC 4: KIỂM TRA & CƯỠNG CHẾ (FALLBACK)
            # ---------------------------------------------------------
            if order.state != 'cancel':
                still_open_picks = order.picking_ids.filtered(lambda p: p.state not in ('cancel', 'done'))
                has_posted_inv = order.invoice_ids.filtered(lambda i: i.state == 'posted')
                if not still_open_picks and not has_posted_inv:
                    order.write({'state': 'cancel'})
                else:
                    return {
                        "ok": False,
                        "error": "cancel_failed",
                        "message": f"Không thể huỷ đơn {name}. Còn picking/invoice chưa huỷ hết."
                    }
                    
            
            if order.state == 'cancel':
                try:
                    # Lấy config Zalo đang active
                    zalo_config = request.env['hlv.zalo.stock.notification'].sudo()._get_active_config()
                    if zalo_config:
                        # Gọi hàm gửi thông báo hủy cho danh sách kho
                        zalo_config.send_cancel_so_notification(order)
                except Exception as e:
                    # Log lỗi nhưng KHÔNG chặn return kết quả API
                    _logger.exception("Failed to send Zalo Cancel Notification for %s: %s", name, e)

            # Kết quả cuối cùng
            return {
                "ok": True, 
                "message": f"Đã huỷ thành công đơn hàng {name}",
                "order_id": order.id,
                "state": order.state
            }

        except Exception as e:
            _logger.exception("MISA API /cancel_by_name exception: %s", e)
            return {"ok": False, "error": "exception", "message": str(e)}
