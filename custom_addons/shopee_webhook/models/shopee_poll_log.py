# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ShopeePollLog(models.Model):
    """Ghi nhận mỗi lần cron poll trạng thái đơn Shopee."""

    _name = 'shopee.poll.log'
    _description = 'Lịch sử Poll Trạng Thái Shopee'
    _order = 'polled_at desc'
    _rec_name = 'polled_at'

    polled_at = fields.Datetime(
        string='Thời điểm poll',
        default=fields.Datetime.now,
        readonly=True,
        index=True,
    )
    total_polled = fields.Integer(string='Tổng đơn kiểm tra', readonly=True)
    changed_count = fields.Integer(string='Đơn thay đổi trạng thái', readonly=True)
    state = fields.Selection(
        [
            ('done', 'Hoàn thành'),
            ('partial', 'Một phần lỗi'),
            ('error', 'Lỗi'),
        ],
        string='Kết quả', default='done', readonly=True,
    )
    error_msg = fields.Text(string='Lỗi', readonly=True)
    line_ids = fields.One2many(
        'shopee.poll.log.line', 'log_id',
        string='Đơn thay đổi',
    )

    def name_get(self):
        result = []
        for rec in self:
            dt = rec.polled_at
            label = dt.strftime('%d/%m/%Y %H:%M') if dt else '?'
            result.append((rec.id, 'Poll %s (%d thay đổi)' % (label, rec.changed_count)))
        return result


class ShopeePollLogLine(models.Model):
    """Chi tiết từng đơn đã đổi trạng thái trong 1 lần poll."""

    _name = 'shopee.poll.log.line'
    _description = 'Chi tiết Poll Trạng Thái Shopee'
    _order = 'id asc'
    _rec_name = 'order_ref'

    log_id = fields.Many2one(
        'shopee.poll.log', string='Lần poll',
        required=True, ondelete='cascade', index=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order', string='Đơn hàng',
        ondelete='set null', index=True,
    )
    order_ref = fields.Char(string='Mã Shopee', index=True)
    shop_name = fields.Char(string='Cửa hàng')
    old_status = fields.Char(string='Trạng thái cũ')
    new_status = fields.Char(string='Trạng thái mới')
    changed = fields.Boolean(
        string='Đã cập nhật',
        default=True,
        help='False nếu write() thất bại.',
    )
    note = fields.Char(string='Ghi chú lỗi')
