# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HlvLoyaltyHistory(models.Model):
    _name = 'hlv.loyalty.history'
    _description = 'Lịch sử điểm Khách hàng thân thiết'
    _order = 'date desc, id desc'
    _rec_name = 'display_name'

    partner_id = fields.Many2one(
        'res.partner', string='Khách hàng', required=True,
        ondelete='cascade', index=True,
    )
    date = fields.Datetime(
        string='Ngày giao dịch', required=True,
        default=fields.Datetime.now,
    )
    point_amount = fields.Integer(string='Số điểm', required=True)
    transaction_type = fields.Selection([
        ('earn', 'Tích điểm'),
        ('redeem', 'Đổi thưởng'),
        ('return', 'Hoàn hàng'),
        ('manual', 'Điều chỉnh thủ công'),
    ], string='Loại giao dịch', required=True, index=True)

    point_type = fields.Selection([
        ('ranking', 'Điểm xếp hạng'),
        ('exchange', 'Điểm đổi thưởng'),
    ], string='Loại điểm', index=True, default='ranking',
        help='Ranking: tự động xác nhận, dùng để tính hạng thành viên.\n'
             'Exchange: cần nhân viên xác nhận, dùng để đổi Voucher.')

    state = fields.Selection([
        ('pending', 'Chờ xác nhận'),
        ('confirmed', 'Đã xác nhận'),
        ('cancelled', 'Đã hủy'),
    ], string='Trạng thái', default='confirmed', index=True, tracking=True)

    description = fields.Char(string='Mô tả')
    point_formula = fields.Text(
        string='Công thức tính điểm',
        readonly=True,
        help='Snapshot công thức và tham số dùng để tính ra số điểm tại thời điểm phát sinh.',
    )
    point_formula_html = fields.Html(
        string='Công thức tính điểm',
        readonly=True,
        sanitize=True,
        help='Phiên bản HTML của công thức tính điểm để đối chiếu chi tiết theo bảng.',
    )

    # Tham chiếu chéo
    picking_id = fields.Many2one('stock.picking', string='Phiếu kho', readonly=True)
    sale_order_id = fields.Many2one('sale.order', string='Đơn bán hàng', readonly=True)
    voucher_id = fields.Many2one('hlv.loyalty.voucher', string='Voucher', readonly=True)

    company_id = fields.Many2one(
        'res.company', string='Chi nhánh phát sinh',
        required=True, default=lambda self: self.env.company,
        index=True,
    )
    company_name = fields.Char(
        string='Tên chi nhánh', related='company_id.name', store=True, readonly=True,
    )

    # Thông tin bổ sung
    sale_company_id = fields.Many2one(
        'res.company', string='Chi nhánh tạo đơn', readonly=True,
        help='Chi nhánh tạo Sale Order (để đối soát)',
    )
    delivery_company_id = fields.Many2one(
        'res.company', string='Chi nhánh giao hàng', readonly=True,
        help='Chi nhánh thực hiện giao hàng (để đối soát)',
    )

    display_name = fields.Char(
        string='Mô tả', compute='_compute_display_name', store=True,
    )

    @api.depends('transaction_type', 'point_amount', 'partner_id')
    def _compute_display_name(self):
        type_labels = dict(self._fields['transaction_type'].selection)
        for rec in self:
            label = type_labels.get(rec.transaction_type, '')
            sign = '+' if rec.point_amount >= 0 else ''
            rec.display_name = f"{label}: {sign}{rec.point_amount} điểm - {rec.partner_id.name or ''}"

    def action_confirm(self):
        """Nhân viên xác nhận điểm đổi thưởng đang chờ."""
        for rec in self:
            if rec.state == 'pending':
                rec.state = 'confirmed'

    def action_cancel(self):
        """Hủy bản ghi điểm đang chờ."""
        for rec in self:
            if rec.state == 'pending':
                rec.state = 'cancelled'

    def action_recalculate_points(self):
        """Tính lại điểm đổi thưởng đang chờ xác nhận, theo dữ liệu mới
        nhất của phiếu giao / dòng bán hàng.

        Dùng khi phiếu đã giao nhưng điểm chưa được xác nhận, và sau đó
        sale sửa lại % CK loyalty trên dòng bán hàng (hoặc khi số liệu
        combo/kit vừa được tính đúng lại) - điểm pending vẫn cần khớp với
        công thức hiện tại vì chưa cộng vào số dư khách hàng.
        """
        for rec in self:
            if rec.point_type != 'exchange' or rec.transaction_type != 'earn':
                raise UserError('Chỉ có thể tính lại điểm đổi thưởng của giao dịch tích điểm.')
            if rec.state != 'pending':
                raise UserError(
                    'Chỉ có thể tính lại điểm khi đang ở trạng thái Chờ xác nhận '
                    '(điểm đã xác nhận đã cộng vào số dư khách hàng).'
                )
            if not rec.picking_id:
                raise UserError('Bản ghi này không gắn với phiếu kho nào để tính lại điểm.')
            rec.picking_id._loyalty_earn_points()
