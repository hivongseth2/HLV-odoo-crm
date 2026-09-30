import logging

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

from ..models.stock_picking import MISA_INVOICE_RECONCILE_GROUP

_logger = logging.getLogger(__name__)

# API cho Claude trên máy worker viết báo cáo đối soát hằng ngày (skill .claude/skills/doi-soat-misa,
# lớp gọi scripts/misa_ai.py). Đăng nhập bằng phiên Odoo của 1 tài khoản worker riêng thuộc nhóm
# "Đối soát XHD" — không mở thêm cơ chế khoá API: mọi route auth='user' và tự kiểm nhóm, quyền đúng
# bằng quyền người đối soát bấm tay trên dashboard. AI chỉ được: đọc số liệu lệch, soát lại theo
# đơn, gửi báo cáo + đề xuất gắn mã đề nghị (người xác nhận mới gắn — misa.invoice.ai.suggestion).


def _ok(data):
    return {'status': 'success', 'data': data}


def _error(message):
    return {'status': 'error', 'message': message}


class MisaInvoiceAiController(http.Controller):

    def _check_group(self):
        if not request.env.user.has_group(MISA_INVOICE_RECONCILE_GROUP):
            raise AccessError("Tài khoản worker phải thuộc nhóm 'Đối soát XHD'.")

    def _run(self, label, func):
        try:
            self._check_group()
            return _ok(func())
        except (UserError, AccessError) as e:
            return _error(str(e))
        except Exception as e:
            _logger.exception('misa ai api %s error', label)
            return _error(str(e))

    @http.route('/misa_invoice/ai/gap_orders', type='json', auth='user', methods=['POST'])
    def gap_orders(self, month='', saler_code='', limit=300, **kwargs):
        return self._run('gap_orders', lambda: request.env['misa.invoice.gap.review'].gap_orders(
            month=month or False, saler_code=saler_code or False, limit=int(limit),
        ))

    @http.route('/misa_invoice/ai/review', type='json', auth='user', methods=['POST'])
    def review(self, order_ids=None, **kwargs):
        return self._run('review', lambda: request.env['misa.invoice.gap.review'].review_orders(order_ids or []))

    @http.route('/misa_invoice/ai/refresh', type='json', auth='user', methods=['POST'])
    def refresh(self, order_ids=None, **kwargs):
        return self._run('refresh', lambda: request.env['misa.invoice.gap.review'].refresh_orders(order_ids or []))

    @http.route('/misa_invoice/ai/last_report', type='json', auth='user', methods=['POST'])
    def last_report(self, **kwargs):
        def last():
            report = request.env['misa.invoice.ai.report'].search([], limit=1)
            return report and {
                'id': report.id, 'report_date': str(report.report_date), 'order_count': report.order_count,
                'total_gap': report.total_gap, 'pending_suggestions': report.suggestion_pending_count,
            } or {}
        return self._run('last_report', last)

    @http.route('/misa_invoice/ai/report', type='json', auth='user', methods=['POST'])
    def submit_report(self, **values):
        return self._run('report', lambda: {'id': request.env['misa.invoice.ai.report'].submit_from_ai(values)})
