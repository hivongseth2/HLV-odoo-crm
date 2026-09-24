# -*- coding: utf-8 -*-
"""Đường cài đặt một lệnh cho máy đóng gói.

Máy mới chưa có gì: chạy một dòng PowerShell, gõ mã cài đặt lấy từ Odoo, xong.
Script tự tải agent + ffmpeg, tự hỏi URL camera, tự đăng ký chạy cùng Windows.

Các route ở đây auth='public' vì máy đóng gói lúc cài chưa đăng nhập Odoo.
Thứ bảo vệ là mã cài đặt dùng một lần, hết hạn sau 30 phút.
"""
import logging

from werkzeug.wrappers import Response

from odoo import http
from odoo.http import request
from odoo.tools import file_open

_logger = logging.getLogger(__name__)

# Chỉ cho tải đúng hai file này, tránh biến route thành cửa đọc file tuỳ ý.
DOWNLOADABLE = {
    'agent': ('hlv_pack_recorder/agent/hlv_pack_agent.py', 'text/plain; charset=utf-8'),
    'setup': ('hlv_pack_recorder/agent/setup.ps1', 'text/plain; charset=utf-8'),
}


class PackSetupApi(http.Controller):

    @http.route('/pack_agent/enroll', type='json', auth='public', csrf=False, methods=['POST'])
    def enroll(self, **kw):
        """Đổi mã cài đặt lấy cấu hình bàn.

        Trả về station_key, token và danh sách camera (mã + tên) để script cài
        biết phải hỏi URL của những camera nào. KHÔNG trả URL camera — Odoo cố ý
        không giữ thứ đó.
        """
        station = request.env['hlv.pack.station'].sudo().consume_enroll_code(kw.get('code'))
        if not station:
            return {'ok': False, 'error': 'Mã cài đặt sai hoặc đã hết hạn.'}

        _logger.info("PACK_REC bàn %s được cài đặt bằng mã", station.name)
        return {
            'ok': True,
            'station_name': station.name,
            'warehouse': station.warehouse_id.name or '',
            'station_key': station.station_key,
            'token': station.agent_token,
            'cameras': [
                {'code': cam.code, 'name': cam.name}
                for cam in station.camera_ids.filtered('active')
            ],
        }

    @http.route('/pack_agent/download/<string:what>', type='http', auth='public', methods=['GET'])
    def download(self, what, **kw):
        """Phục vụ script agent và script cài đặt.

        Để Odoo làm nguồn duy nhất: sửa agent xong thì máy nào chạy lại script
        cài là có bản mới, khỏi đi chép tay từng máy.
        """
        entry = DOWNLOADABLE.get(what)
        if not entry:
            return Response('not found', status=404)
        path, content_type = entry
        try:
            with file_open(path, 'rb') as fh:
                content = fh.read()
        except (FileNotFoundError, OSError):
            _logger.exception("PACK_REC không đọc được %s", path)
            return Response('unavailable', status=500)
        return Response(content, status=200, content_type=content_type)
