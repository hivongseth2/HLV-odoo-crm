# -*- coding: utf-8 -*-
"""Endpoint nhận heartbeat từ script watchdog chạy TRÊN MÁY CHỦ KHO (bin/iot_watchdog_windows.ps1).

Vì sao cần: Odoo KHÔNG có cách tự biết máy chủ kho (máy chạy service IoT + nối máy in) còn sống
hay không — iot.device.connected có thể giữ True mãi sau khi hộp IoT chết đột ngột, còn write_date
của device không phải heartbeat liên tục (xem models/iot_print_queue.py, IOT_DEVICE_STALE_SECONDS).
Nguồn tin cậy duy nhất là chính máy đó tự báo về theo chu kỳ.

Auth: auth='public' + token dùng chung (ir.config_parameter
hlv_sale_delivery_planning.iot_watchdog_token) — đây là endpoint máy-gọi-máy, không có phiên đăng
nhập người dùng trên máy chủ kho. Endpoint chỉ ghi được duy nhất 3 field watchdog của kho
(không đọc/sửa dữ liệu nghiệp vụ nào khác), nên rủi ro giới hạn ở mức "ai có token thì báo được
trạng thái sai" — chấp nhận được, đổi token là xong.
"""
import hmac
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class IotWatchdogController(http.Controller):

    def _check_token(self, token):
        expected = request.env['ir.config_parameter'].sudo().get_param(
            'hlv_sale_delivery_planning.iot_watchdog_token'
        ) or ''
        if not expected:
            # Chưa cấu hình token = tính năng chưa bật, không nhận heartbeat (tránh mở cửa
            # cho bất kỳ ai ghi trạng thái khi admin còn chưa biết endpoint này tồn tại).
            return False, 'Chưa cấu hình iot_watchdog_token trong Settings > HLV Delivery Planner.'
        if not token or not hmac.compare_digest(str(token), str(expected)):
            return False, 'Token không đúng.'
        return True, ''

    @http.route('/api/iot_watchdog/heartbeat', type='json', auth='public',
                methods=['POST'], csrf=False)
    def iot_watchdog_heartbeat(self, token=None, warehouse_code=None, service_ok=None,
                               note='', printed_total=None, **kwargs):
        """Script trên máy chủ kho gọi mỗi 1-2 phút. Body JSON-RPC params:
            token: chuỗi bí mật dùng chung (bắt buộc)
            warehouse_code: MÃ KHO trong Odoo (stock.warehouse.code, VD 'KBC', 'TSN')
            service_ok: true/false — service Odoo IoT trên máy đó có đang Running không
            note: chuỗi ghi chú tuỳ ý (tên máy, trạng thái máy in, đã tự restart chưa...)
            printed_total: TỔNG số job Windows đã in trên máy in của kho (performance counter
              '\\Print Queue(...)\\Total Jobs Printed'). Odoo dùng con số này để ĐỐI CHIẾU với
              số lệnh in đã dispatch, phát hiện phiếu "đã gửi lệnh in" mà không ra giấy — xem
              stock_warehouse._iot_reconcile_printed_jobs(). Bỏ trống = không đối chiếu.
        """
        ok, err = self._check_token(token)
        if not ok:
            _logger.warning('IoT watchdog heartbeat bị từ chối: %s', err)
            return {'success': False, 'message': err}
        try:
            return request.env['stock.warehouse'].sudo().iot_watchdog_heartbeat(
                warehouse_code, service_ok, note=note, printed_total=printed_total,
            )
        except Exception as e:
            _logger.exception('IoT watchdog heartbeat lỗi')
            return {'success': False, 'message': str(e)}

    @http.route('/api/iot_watchdog/claim_print_jobs', type='json', auth='public',
                methods=['POST'], csrf=False)
    def iot_watchdog_claim_print_jobs(self, token=None, warehouse_code=None, limit=5, **kwargs):
        """MÁY KHO TỰ NHẬN VIỆC IN — đường in không cần trình duyệt.

        Đường in qua hộp IoT bắt buộc phải có TRÌNH DUYỆT đang mở trang "Điều phối Giao hàng"
        (server Odoo.sh không vào được LAN kho), nên đóng tab là hàng chờ nằm im. Route này lật
        chiều lại: máy kho hỏi "có việc gì cho tôi không", nhận PDF rồi in bằng driver máy in
        Windows của chính nó.

        Params: token, warehouse_code (stock.warehouse.code), limit (1-20, mặc định 5).
        Trả về: jobs = [{queue_id, sale_order_name, picking_names, filename, pdf_b64}].
        Bản ghi được giữ ở 'printing' cho tới khi máy kho gọi /report_print_result.
        """
        ok, err = self._check_token(token)
        if not ok:
            _logger.warning('IoT claim_print_jobs bị từ chối: %s', err)
            return {'success': False, 'message': err}
        try:
            return request.env['hlv.iot.print.queue'].sudo().claim_for_local_dispatcher(
                warehouse_code, limit=limit,
            )
        except Exception as e:
            _logger.exception('IoT claim_print_jobs lỗi')
            return {'success': False, 'message': str(e)}

    @http.route('/api/iot_watchdog/report_print_result', type='json', auth='public',
                methods=['POST'], csrf=False)
    def iot_watchdog_report_print_result(self, token=None, warehouse_code=None, results=None,
                                        **kwargs):
        """Máy kho báo kết quả in thật của các job vừa nhận từ /claim_print_jobs.

        Params: token, warehouse_code, results = [{queue_id, success, message, printer}].
        In được -> 'Đã gửi lệnh in'; lỗi -> 'Lỗi' kèm lý do (hiện ngay trong hàng chờ, không im
        lặng bỏ qua). Không báo gì -> bản ghi vẫn ở 'printing' và sẽ được đưa lại hàng chờ sau
        STALE_PRINTING_RECLAIM_MINUTES phút.
        """
        ok, err = self._check_token(token)
        if not ok:
            return {'success': False, 'message': err}
        try:
            return request.env['hlv.iot.print.queue'].sudo().report_local_dispatch_result(
                warehouse_code, results or [],
            )
        except Exception as e:
            _logger.exception('IoT report_print_result lỗi')
            return {'success': False, 'message': str(e)}

    @http.route('/api/iot_watchdog/status', type='json', auth='public',
                methods=['POST'], csrf=False)
    def iot_watchdog_status(self, token=None, **kwargs):
        """Trả về tình trạng hiện tại của tất cả kho có máy in IoT — để script/máy chủ kho tự
        kiểm tra lại xem Odoo đang thấy mình thế nào (debug tại chỗ, không cần mở Odoo)."""
        ok, err = self._check_token(token)
        if not ok:
            return {'success': False, 'message': err}
        Queue = request.env['hlv.iot.print.queue'].sudo()
        return {'success': True, 'printer_status': Queue.get_printer_status_by_warehouse()}
