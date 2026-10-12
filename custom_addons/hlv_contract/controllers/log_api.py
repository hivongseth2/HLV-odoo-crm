# -*- coding: utf-8 -*-
"""Trang /hop-dong — nhật ký hợp đồng: của một hợp đồng (ngăn soạn) và toàn bộ (Quản lý,
gồm cả hợp đồng đã xoá). Chỉ đọc; record rule giới hạn nhân viên ở hợp đồng mình phụ trách."""

from odoo import fields, http
from odoo.http import request

from ..models.contract_log import ACTIONS
from .common import API, ContractPageMixin, to_int

PER_PAGE = 50
ACTION_LABELS = dict(ACTIONS)


def log_row(log):
    when = fields.Datetime.context_timestamp(log, log.create_date)
    return {
        'id': log.id,
        'date': when.strftime('%d/%m/%Y %H:%M'),
        'user': log.user_id.name or '',
        'contract_id': log.contract_id.id or False,
        'contract_name': log.contract_name or '',
        'action': log.action,
        'action_label': ACTION_LABELS.get(log.action, log.action),
        'summary': log.summary or '',
        'details': (log.details or '').split('\n') if log.details else [],
    }


class ContractLogPage(ContractPageMixin, http.Controller):

    @http.route(f'{API}/logs', type='json', auth='user', methods=['POST'])
    def api_logs(self, contract_id=None, **kw):
        """Nhật ký của một hợp đồng, mới nhất trước."""
        self._check()
        contract = self._get_record('hlv.contract', contract_id)
        logs = request.env['hlv.contract.log'].search([('contract_id', '=', contract.id)], limit=200)
        return [log_row(log) for log in logs]

    @http.route(f'{API}/logs/all', type='json', auth='user', methods=['POST'])
    def api_logs_all(self, search='', action='', page=1, **kw):
        """Toàn bộ nhật ký (Quản lý): tìm theo số hợp đồng / người làm / nội dung, lọc theo việc."""
        self._check_manager()
        Log = request.env['hlv.contract.log']
        domain = []
        term = (search or '').strip()
        if term:
            domain += ['|', '|', '|', ('contract_name', 'ilike', term), ('user_id.name', 'ilike', term),
                       ('summary', 'ilike', term), ('details', 'ilike', term)]
        if action in ACTION_LABELS:
            domain.append(('action', '=', action))
        total = Log.search_count(domain)
        page = max(1, to_int(page) or 1)
        logs = Log.search(domain, offset=(page - 1) * PER_PAGE, limit=PER_PAGE)
        return {
            'logs': [log_row(log) for log in logs],
            'page': page,
            'pages': max(1, -(-total // PER_PAGE)),
            'total': total,
            'actions': ACTIONS,
        }
