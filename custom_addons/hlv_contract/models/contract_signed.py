# -*- coding: utf-8 -*-
"""Bản scan đã ký (PDF) lưu kèm từng hợp đồng / phụ lục / đề nghị thanh toán.

Không thuộc nội dung hợp đồng nên tải lên được ở mọi trạng thái (thường là lúc đã xác nhận, khách
ký xong gửi lại). Mỗi văn bản giữ một bản đang dùng; thay file hay xoá đều ghi nhật ký kèm tên file
cũ. Xoá chỉ Quản lý được làm — bản đã ký là chứng từ.
"""

import base64

from odoo import fields, models
from odoo.exceptions import AccessError, UserError

from .contract import _NO_AUDIT

MAX_SIGNED_BYTES = 20 * 1024 * 1024


class ContractSigned(models.Model):
    _inherit = 'hlv.contract'

    signed_file = fields.Binary(string='Bản scan đã ký', attachment=True, copy=False)
    signed_filename = fields.Char(string='Tên file bản ký', copy=False)
    signed_uploaded_at = fields.Datetime(string='Tải bản ký lúc', copy=False, readonly=True)
    signed_uploaded_by = fields.Many2one('res.users', string='Người tải bản ký', copy=False, readonly=True)

    def set_signed_file(self, filename, data):
        """Lưu bản scan đã ký. data: bytes PDF. Không phải PDF / quá 20 MB -> UserError."""
        self.ensure_one()
        if not data or len(data) > MAX_SIGNED_BYTES:
            raise UserError('File rỗng hoặc lớn hơn 20 MB.')
        # Kiểm theo nội dung, không theo đuôi: ảnh chụp đổi tên thành .pdf vẫn bị chặn
        if not data[:1024].lstrip().startswith(b'%PDF'):
            raise UserError('Chỉ nhận file PDF. Ảnh chụp hãy gộp thành PDF trước (vd dùng app scan trên điện thoại).')
        old_name = self.signed_filename
        name = (filename or '').strip() or '%s - ban ky.pdf' % self.name
        self.with_context(**{_NO_AUDIT: True}).write({
            'signed_file': base64.b64encode(data),
            'signed_filename': name,
            'signed_uploaded_at': fields.Datetime.now(),
            'signed_uploaded_by': self.env.uid,
        })
        self._log('signed', 'Thay bản scan đã ký: %s → %s' % (old_name, name) if old_name
                  else 'Tải lên bản scan đã ký: %s' % name)

    def clear_signed_file(self):
        self.ensure_one()
        if not self._is_manager():
            raise AccessError('Chỉ Quản lý hợp đồng được xoá bản scan đã ký.')
        if self.signed_filename:
            name = self.signed_filename
            self.with_context(**{_NO_AUDIT: True}).write({
                'signed_file': False, 'signed_filename': False, 'signed_uploaded_at': False, 'signed_uploaded_by': False,
            })
            self._log('signed', 'Xoá bản scan đã ký: %s' % name)

    def _signed_bytes(self):
        self.ensure_one()
        data = self.sudo().with_context(bin_size=False).signed_file
        return base64.b64decode(data) if data else b''

    def _signed_info(self):
        """Thông tin bản ký cho trang; chưa có -> False."""
        self.ensure_one()
        if not self.signed_filename:
            return False
        return {
            'filename': self.signed_filename,
            'uploaded_at': fields.Datetime.to_string(self.signed_uploaded_at) if self.signed_uploaded_at else '',
            'uploaded_by': self.signed_uploaded_by.sudo().name or '',
            'url': '/hop-dong/ban-ky/%d' % self.id,
        }
