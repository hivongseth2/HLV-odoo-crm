# -*- coding: utf-8 -*-
"""Cài agent bằng một lệnh.

Máy chạy Claude chỉ cần dán một dòng PowerShell, gõ mã cài đặt lấy từ Odoo, xong.
Script tự tải agent từ đây, tự lấy token, tự đăng ký chạy cùng Windows. Prompt KHÔNG
tải ở đây: agent tự lấy qua /product_agent/agent/prompt mỗi khi nó đổi trên Odoo.

auth='public' vì lúc cài máy chưa có gì để xác thực. Thứ bảo vệ là mã cài đặt dùng
một lần, hết hạn sau 30 phút; các file tải về chỉ là mã nguồn agent — không có bí
mật nào.
"""
import logging

from werkzeug.wrappers import Response

from odoo import http
from odoo.http import request
from odoo.tools import file_open

_logger = logging.getLogger(__name__)

TEXT = 'text/plain; charset=utf-8'
# Chỉ cho tải đúng các file này, tránh biến route thành cửa đọc file tuỳ ý.
# Khoá là tên script cài đặt dùng để tải; giá trị là (đường dẫn trong addons, tên lưu).
DOWNLOADABLE = {
    'setup': ('hlv_product_agent/agent/setup.ps1', 'setup.ps1'),
    'agent': ('hlv_product_agent/agent/hlv_product_agent.py', 'hlv_product_agent.py'),
    'mcp_server': ('hlv_product_agent/agent/misa_mcp_server.py', 'misa_mcp_server.py'),
    'tools': ('hlv_product_agent/agent/misa_tools.py', 'misa_tools.py'),
}


class ProductAgentSetupApi(http.Controller):

    @http.route('/product_agent/enroll', type='json', auth='public', csrf=False, methods=['POST'])
    def enroll(self, **kw):
        """Đổi mã cài đặt lấy token agent."""
        agent = request.env['hlv.product.agent'].sudo().consume_enroll_code(kw.get('code'))
        if not agent:
            return {'ok': False, 'error': 'Mã cài đặt sai hoặc đã hết hạn.'}
        _logger.info("PRODUCT_AGENT máy '%s' được cài bằng mã", agent.name)
        return {'ok': True, 'agent_name': agent.name, 'token': agent.token}

    @http.route('/product_agent/download/manifest', type='http', auth='public', methods=['GET'])
    def manifest(self, **kw):
        """Danh sách file agent cần, mỗi dòng ``<khoá> <tên lưu>``.

        Script cài đọc danh sách từ đây thay vì tự liệt kê, để thêm file vào agent chỉ
        phải sửa một chỗ (DOWNLOADABLE).
        """
        lines = ['%s %s' % (key, target) for key, (_path, target) in DOWNLOADABLE.items() if key != 'setup']
        return Response('\n'.join(lines) + '\n', status=200, content_type=TEXT)

    @http.route('/product_agent/download/<string:what>', type='http', auth='public', methods=['GET'])
    def download(self, what, **kw):
        """Phục vụ script cài đặt và các file của agent.

        Odoo là nguồn duy nhất: sửa agent hay tài liệu quy tắc xong, máy chạy lại lệnh
        cài là có bản mới, khỏi chép tay.
        """
        entry = DOWNLOADABLE.get(what)
        if not entry:
            return Response('not found', status=404)
        try:
            with file_open(entry[0], 'rb') as handle:
                content = handle.read()
        except (FileNotFoundError, OSError):
            _logger.exception("PRODUCT_AGENT không đọc được %s", entry[0])
            return Response('unavailable', status=500)
        return Response(content, status=200, content_type=TEXT)
