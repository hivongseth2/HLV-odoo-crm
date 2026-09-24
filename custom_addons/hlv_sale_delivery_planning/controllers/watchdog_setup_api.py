# -*- coding: utf-8 -*-
"""Đường cài watchdog máy kho bằng MỘT LỆNH.

Máy kho mới (hoặc máy vừa cài lại) không có repo, cũng không tiện chép file qua
UltraViewer. Ở đây Odoo làm nguồn phát script: dán một dòng PowerShell là máy tự tải
script về, hỏi thông số, lưu cấu hình và đăng ký tác vụ chạy nền.

Đi theo đúng khuôn đã dùng cho agent ghi hình đóng gói
(hlv_pack_recorder/controllers/setup_api.py) — một khuôn cho mọi agent chạy ở máy kho,
đừng đẻ thêm kiểu thứ hai.

auth='public' vì máy kho lúc cài chưa đăng nhập Odoo. Ba file phục vụ ở đây KHÔNG chứa bí
mật nào: token watchdog do người cài gõ vào lúc chạy và chỉ nằm ở C:\\ProgramData của máy
đó. Ai tải được script cũng không làm gì được nếu không có token.
"""
import logging

from werkzeug.wrappers import Response

from odoo import http
from odoo.tools import file_open

_logger = logging.getLogger(__name__)

# Chỉ cho tải đúng ba file này — không biến route thành cửa đọc file tuỳ ý.
DOWNLOADABLE = {
    'setup': ('hlv_sale_delivery_planning/agent/setup_watchdog.ps1',
              'text/plain; charset=utf-8'),
    'watchdog': ('hlv_sale_delivery_planning/agent/iot_watchdog_windows.ps1',
                 'text/plain; charset=utf-8'),
    'hidden': ('hlv_sale_delivery_planning/agent/run_watchdog_hidden.vbs',
               'text/plain; charset=utf-8'),
}


class IotWatchdogSetupApi(http.Controller):

    @http.route('/iot_watchdog/download/<string:what>', type='http', auth='public',
                methods=['GET'])
    def download(self, what, **kw):
        """Phục vụ script cài đặt và hai file watchdog.

        Để Odoo làm nguồn duy nhất: sửa watchdog xong, máy kho chạy lại một lệnh là có bản
        mới — khỏi đi chép tay từng máy, và khỏi cảnh mỗi kho chạy một phiên bản khác nhau.
        """
        entry = DOWNLOADABLE.get(what)
        if not entry:
            return Response('not found', status=404)
        path, content_type = entry
        try:
            with file_open(path, 'rb') as fh:
                content = fh.read()
        except (FileNotFoundError, OSError):
            _logger.exception('IOT_WATCHDOG không đọc được %s', path)
            return Response('unavailable', status=500)
        return Response(content, status=200, content_type=content_type)
