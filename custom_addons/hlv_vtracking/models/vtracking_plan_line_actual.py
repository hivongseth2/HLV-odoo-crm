"""Số thực tế của một điểm giao: giao lúc nào, có bị chở về không, lệch bao nhiêu phút.

Tách khỏi ``vtracking_plan_line.py`` vì đây là nguồn dữ liệu KHÁC: mọi ô ở đây do phiếu
giao và app shipper sinh ra, không do người điều phối nhập. Trộn chung vào file kia thì đọc
code không còn phân biệt được đâu là dự kiến, đâu là đã xảy ra.

Tất cả đều ``readonly`` và ``copy=False``: sao chép một kế hoạch cũ mà kéo theo giờ giao
của nó là tạo ra dữ liệu thực tế giả.
"""

from odoo import fields, models


class HlvVtrackingPlanLineActual(models.Model):
    _inherit = 'hlv.vtracking.plan.line'

    returned = fields.Boolean(
        string='Chở về', readonly=True, copy=False, index=True,
        help='Shipper đã tới nơi nhưng không giao được, hàng chở ngược về kho. Một điểm như '
             'vậy vẫn TỐN thời gian và quãng đường của chuyến, nên phải đếm riêng.',
    )
    return_reason = fields.Char(string='Lý do chở về', readonly=True, copy=False)
    received_at = fields.Datetime(
        string='Hàng lên xe lúc', readonly=True, copy=False,
        help='Lúc shipper quét nhận phiếu tại kho.',
    )
    shipper_id = fields.Many2one(
        'res.users', string='Người giao', readonly=True, copy=False,
        help='Ai thật sự chở chuyến này — có thể khác tài xế khai trên Đội xe.',
    )
    variance_minutes = fields.Integer(
        string='Lệch giờ (phút)', readonly=True, copy=False,
        help='Thực tế trừ kế hoạch. Dương = tới chậm hơn dự kiến. Để trống nghĩa là chưa đo '
             'được, khác hẳn 0 nghĩa là đúng y hẹn.',
    )
