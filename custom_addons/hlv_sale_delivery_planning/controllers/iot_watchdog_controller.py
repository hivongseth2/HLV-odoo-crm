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
