# -*- coding: utf-8 -*-
"""Phần dùng chung của các controller trang /hop-dong: kiểm quyền, lấy record an toàn.

Mọi API chạy bằng quyền user đăng nhập (không sudo): record rule của module tự giới hạn
nhân viên chỉ thấy hợp đồng mình phụ trách.
"""

from odoo.exceptions import AccessError, UserError
from odoo.http import request

from ..models.contract import MANAGER_GROUP

PAGE_ROUTE = '/hop-dong'
API = '/api/hop-dong'
USER_GROUP = 'hlv_contract.group_contract_user'


def to_int(value):
    """'12' / 12 -> 12; None, '', chữ -> 0."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_ids(value):
    """'1,2,3' hoặc [1, 2] -> [1, 2, 3], bỏ giá trị không phải số."""
    items = value.split(',') if isinstance(value, str) else (value or [])
    return [i for i in (to_int(v) for v in items) if i]


class ContractPageMixin:

    def _allowed(self):
        return request.env.user.has_group(USER_GROUP)

    def _is_manager(self):
        return request.env.user.has_group(MANAGER_GROUP)

    def _check(self):
        if not self._allowed():
            raise AccessError('Tài khoản chưa được cấp quyền dùng trang Hợp đồng.')

    def _check_manager(self):
        self._check()
        if not self._is_manager():
            raise AccessError('Chỉ Quản lý hợp đồng được làm thao tác này.')

    def _get_record(self, model, record_id):
        """Record theo id, đã kiểm quyền đọc (record rule) — không mở được hợp đồng của người
        khác bằng cách đoán id."""
        record = request.env[model].browse(to_int(record_id)).exists()
        if not record:
            raise UserError('Không tìm thấy bản ghi.')
        record.check_access('read')
        return record
