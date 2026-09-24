"""Trang `/giao-hang` cho người bán hàng: xem chuyến, xem xe đang ở đâu, nhờ AI xếp lịch.

Người bán hàng KHÔNG có quyền trên model kế hoạch và không cần có. Trang này chạy bằng
``sudo`` ở tầng service và chỉ trả đúng những ô đã liệt kê ở ``services/sale_board``.

Không dùng khoá API như nhóm `/api/v1/ai/*`: bên gọi ở đây là trình duyệt của một người
đã đăng nhập Odoo, nên phiên đăng nhập chính là thứ xác thực.
"""

import logging
from datetime import datetime

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

from ..services import sale_board, sale_board_document

_logger = logging.getLogger(__name__)

REQUEST_TYPES = ('earlier', 'reschedule', 'add', 'remove', 'question')
MAX_MESSAGE_LENGTH = 2000


def _check_internal():
    """Chỉ người dùng nội bộ. Khách trên cổng thông tin không được xem lịch xe của công ty."""
    if request.env.user.share:
        raise AccessError('Trang này chỉ dành cho nhân viên.')


class VtrackingSaleBoardController(http.Controller):

    @http.route('/giao-hang', type='http', auth='user', website=False)
    def sale_board_page(self, **_kwargs):
        _check_internal()
        return request.render('hlv_vtracking.sale_board_page', {
            'user_name': request.env.user.name,
        })

    @http.route('/giao-hang/du-lieu', type='json', auth='user')
    def board_data(self, date=None, saler_code=None, search=None, **_kwargs):
        _check_internal()
        return sale_board.board_data(request.env, _parse_date(date),
                                     _clean_text(saler_code), _clean_text(search))

    @http.route('/giao-hang/don-chua-xep', type='json', auth='user')
    def unplanned_orders(self, saler_code=None, search=None, **_kwargs):
        """Chỉ danh sách đơn chưa xếp — gõ vào ô tìm kiếm không cần tải lại cả trang."""
        _check_internal()
        return {'my_unplanned': sale_board.my_unplanned_orders(
            request.env, _clean_text(saler_code), _clean_text(search))}

    @http.route('/giao-hang/vi-tri', type='json', auth='user')
    def vehicle_positions(self, **_kwargs):
        """Chỉ vị trí xe — trang gọi lại theo chu kỳ nên phải nhẹ."""
        _check_internal()
        return sale_board.vehicle_positions(request.env)

    @http.route('/giao-hang/chung-tu', type='json', auth='user')
    def document_detail(self, kind=None, id=None, **_kwargs):
        """Xem nhanh một đơn bán hoặc phiếu kho ngay trên trang."""
        _check_internal()
        if kind not in ('order', 'picking') or not id:
            raise UserError('Thiếu chứng từ cần xem.')
        return sale_board_document.document_detail(request.env, kind, id)

    @http.route('/giao-hang/yeu-cau', type='json', auth='user')
    def create_request(self, **values):
        """Gửi yêu cầu cho AI. Trả về danh sách yêu cầu đã cập nhật để trang vẽ lại."""
        _check_internal()
        try:
            return sale_board.create_request(request.env, _clean_request(values))
        except UserError as exc:
            return {'error': str(exc.args[0] if exc.args else exc)}


def _clean_text(value):
    """Chuỗi từ trình duyệt -> chuỗi đã cắt, hoặc None. Giới hạn độ dài: ô tìm kiếm đi
    thẳng vào domain, không để ai dán cả trang văn bản vào đó."""
    text = (value or '').strip()
    return text[:80] or None


def _parse_date(value):
    """Chuỗi YYYY-MM-DD -> date. Rỗng hoặc sai dạng thì về hôm nay, không báo lỗi: tham số
    này đến từ ô chọn ngày trên trang, sai là do người gõ tay vào URL."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except ValueError:
        return None


def _clean_request(values):
    """Dữ liệu từ trình duyệt -> giá trị tin được. Không tin bất cứ ô nào gửi lên."""
    request_type = values.get('request_type')
    if request_type not in REQUEST_TYPES:
        raise UserError('Loại yêu cầu không hợp lệ.')
    message = (values.get('message') or '').strip()
    if not message:
        raise UserError('Viết vài dòng cho AI biết bạn cần gì.')
    if not (values.get('sale_order_id') or values.get('plan_id')):
        raise UserError('Chọn đơn hàng hoặc chuyến mà yêu cầu nói tới.')
    return {
        'request_type': request_type,
        'message': message[:MAX_MESSAGE_LENGTH],
        'sale_order_id': int(values['sale_order_id']) if values.get('sale_order_id') else None,
        'plan_id': int(values['plan_id']) if values.get('plan_id') else None,
        'desired_date': values.get('desired_date') or None,
        'desired_session': values.get('desired_session') or None,
    }
