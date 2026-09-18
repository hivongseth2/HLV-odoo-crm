"""Đối chiếu kế hoạch với thực tế ở mức cả chuyến.

Tách khỏi ``vtracking_plan.py`` cùng lý do với dòng kế hoạch: đây là nguồn dữ liệu khác, và
là nơi duy nhất được phép ghi vào các ô ``actual_*``.
"""

import logging

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

from ..services import vtracking_actual
from ..tools.vtracking_actual import (
    ON_TIME_TOLERANCE_MINUTES, leg_variance, minutes_between, summarize_variance,
)
from ..tools.vtracking_route import estimate_legs, format_minutes

_logger = logging.getLogger(__name__)

# Số ngày lùi lại khi tác vụ nền đọc số thực tế. Hai ngày chứ không phải một: phiếu của
# chiều muộn hay được xác nhận sang hôm sau, và kế hoạch cuối tuần thì tới thứ Hai mới xong.
ACTUAL_LOOKBACK_DAYS = 2


class HlvVtrackingPlanActual(models.Model):
    _inherit = 'hlv.vtracking.plan'

    actual_returned_count = fields.Integer(
        string='Số phiếu chở về', readonly=True, copy=False,
        help='Điểm đã tới nhưng không giao được. Tốn thời gian và quãng đường y như một điểm '
             'giao thành công, nên phải đếm riêng chứ không bỏ qua.',
    )
    actual_start_source = fields.Selection(
        [('received', 'Lúc hàng lên xe'), ('done', 'Lúc giao điểm đầu'), ('none', 'Chưa có')],
        string='Mốc xuất phát lấy từ', readonly=True, copy=False, default='none',
        help='"Lúc giao điểm đầu" là mốc LÙI — thời lượng chuyến tính ra sẽ ngắn hơn thực tế '
             'vì thiếu chặng từ kho ra điểm đầu.',
    )
    actual_duration_display = fields.Char(
        compute='_compute_actual_duration', string='Thời gian thực tế',
    )
    variance_summary = fields.Char(
        compute='_compute_variance_summary', string='Đối chiếu giờ giấc',
    )

    @api.depends('actual_start_at', 'actual_end_at')
    def _compute_actual_duration(self):
        for plan in self:
            minutes = minutes_between(plan.actual_start_at, plan.actual_end_at)
            plan.actual_duration_display = format_minutes(minutes) if minutes else ''

    @api.depends('line_ids.variance_minutes', 'line_ids.delivered_at', 'actual_line_count')
    def _compute_variance_summary(self):
        for plan in self:
            summary = plan._variance_summary()
            plan.variance_summary = (
                '%s/%s điểm đúng hẹn · lệch trung bình %+d phút · dao động %d phút'
                % (summary['on_time'], summary['measured'],
                   summary['mean_variance'], summary['mean_abs_variance'])
            ) if summary['measured'] else ''

    def _variance_summary(self):
        """Tóm tắt chênh lệch giờ giấc của cả chuyến. Dùng cho màn hình lẫn API.

        Chỉ tính các điểm ĐÃ GIAO: điểm chưa giao thì lệch 0 phút không có nghĩa gì, mà đưa
        vào trung bình lại kéo con số về phía "đúng hẹn" một cách giả tạo.
        """
        self.ensure_one()
        return summarize_variance([
            {'variance': line.variance_minutes,
             'on_time': abs(line.variance_minutes) <= ON_TIME_TOLERANCE_MINUTES}
            for line in self.line_ids if line.delivered_at
        ])

    def action_refresh_actual(self):
        """Đọc lại số thực tế từ phiếu giao và lịch sử GPS."""
        filled = vtracking_actual.fill_plan_actuals(self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Đối chiếu thực tế',
                'message': 'Đã đọc lại %s/%s kế hoạch có dữ liệu thực tế.' % (filled, len(self)),
                'type': 'success' if filled else 'warning',
                'sticky': False,
            },
        }

    @api.model
    def _cron_fill_actuals(self, days=ACTUAL_LOOKBACK_DAYS):
        """Tác vụ nền: đọc số thực tế cho các kế hoạch vừa chạy xong.

        Chỉ quét ``confirmed`` và ``done``: kế hoạch nháp chưa ai chạy, còn kế hoạch huỷ thì
        số thực tế của những phiếu đó thuộc về một chuyến khác.
        """
        cutoff = fields.Date.context_today(self) - relativedelta(days=days)
        plans = self.search([
            ('date', '>=', cutoff),
            ('state', 'in', ('confirmed', 'done')),
        ])
        filled = vtracking_actual.fill_plan_actuals(plans)
        _logger.info('V-Tracking: đọc số thực tế cho %s/%s kế hoạch.', filled, len(plans))
        return filled

    def vs_actual(self):
        """Bảng đối chiếu từng điểm, cho màn hình và cho API.

        Trả về dict ``{'summary', 'stops'}``. Mỗi phần tử ``stops`` có cả giờ dự kiến lẫn giờ
        đo được (phút tính từ lúc xuất phát) và chênh lệch giữa hai bên.
        """
        self.ensure_one()
        lines = self._ordered_lines()
        planned = [leg['arrive_offset_minutes'] for leg in estimate_legs(
            self._route_start(), self._route_stops(), self._route_params(),
            self._route_extra_minutes(),
        )]
        actual = [minutes_between(self.actual_start_at, line.delivered_at) for line in lines]
        items = leg_variance(planned, actual)
        stops = [
            dict(
                items[index],
                line_id=line.id,
                seq_no=index + 1,
                reference=line.display_reference,
                zone_name=line.zone_id.name or None,
                delivered=line.delivered,
                returned=line.returned,
                return_reason=line.return_reason or None,
            )
            for index, line in enumerate(lines)
        ]
        return {
            'summary': summarize_variance(items),
            'start_source': self.actual_start_source,
            'stops': stops,
        }
