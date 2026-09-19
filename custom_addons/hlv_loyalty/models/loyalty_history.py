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
        help='Công ty gốc (để đối soát/rollup) — không phải nơi giữ số dư có thể '
             'tiêu, xem account_id.',
    )
    account_id = fields.Many2one(
        'hlv.loyalty.portal.account', string='Tài khoản Loyalty',
        ondelete='cascade', index=True,
        help='Tài khoản Loyalty thực sự sở hữu điểm này. Mỗi công ty có thể có '
             'nhiều tài khoản, mỗi tài khoản có số dư riêng.',
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
        ('transfer', 'Chuyển điểm'),
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
    cancel_reason = fields.Selection([
        ('return', 'Hoàn hàng'),
        ('revoke', 'Thu hồi thủ công'),
    ], string='Lý do hủy', readonly=True, copy=False,
        help='Phân biệt bản ghi bị hủy do hoàn hàng (điểm không được tích lại, '
             'vì hàng đã trả) với bản ghi bị người dùng chủ động hủy/thu hồi '
             '(được phép tích lại qua nút "Tạo bù điểm Loyalty").')

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
                rec.write({'state': 'cancelled', 'cancel_reason': 'revoke'})

    @api.model
    def _get_picking_ranking_total(self, picking):
        """Tổng điểm xếp hạng còn hiệu lực đã ghi cho 1 phiếu kho.

        Nhận: recordset `stock.picking` (1 bản ghi).
        Trả: tổng `point_amount` của mọi tài khoản, bỏ bản ghi đã hủy; 0 nếu
        phiếu chưa có bản ghi nào.
        """
        return sum(self.sudo().search([
            ('picking_id', '=', picking.id),
            ('transaction_type', '=', 'earn'),
            ('point_type', '=', 'ranking'),
            ('state', '!=', 'cancelled'),
        ]).mapped('point_amount'))

    def action_revoke_points(self):
        """Thu hồi điểm của bản ghi đang mở.

        Khác `action_cancel` (chỉ hủy được bản ghi đang chờ): hàm này thu hồi
        được cả điểm ĐÃ xác nhận — tức đã vào số dư khách — nên dùng khi cần
        sửa sai (vd điểm tích nhầm tài khoản).
        """
        self.ensure_one()
        if self.transaction_type != 'earn':
            raise UserError('Chỉ thu hồi được điểm của giao dịch Tích điểm.')
        if self.state != 'confirmed':
            raise UserError(
                'Chỉ thu hồi được điểm ĐÃ xác nhận (điểm đã vào số dư khách). '
                'Bản ghi đang chờ xác nhận thì dùng nút "Hủy".'
            )

        # Bản ghi hoàn hàng đối ứng phải bị hủy cùng lúc, nếu không số dư sẽ
        # âm: phần cộng biến mất còn phần trừ vẫn nằm lại. Không tự ghép cặp ở
        # đây vì bản ghi hoàn hàng gắn với PHIẾU HOÀN chứ không phải phiếu giao
        # gốc — ghép theo đơn + tài khoản có thể trúng nhầm phiếu giao khác của
        # cùng đơn. Chặn lại và đẩy sang nút thu hồi trọn gói trên đơn.
        if self.sale_order_id and self.sudo().search_count([
            ('sale_order_id', '=', self.sale_order_id.id),
            ('account_id', '=', self.account_id.id),
            ('point_type', '=', self.point_type),
            ('transaction_type', '=', 'return'),
            ('state', '!=', 'cancelled'),
        ]):
            raise UserError(
                'Đơn này đã có giao dịch hoàn hàng cho cùng tài khoản và loại điểm. '
                'Hãy dùng nút "Thu hồi toàn bộ điểm" trên đơn bán hàng để thu hồi '
                'trọn gói, tránh để số dư âm.'
            )

        return self._revoke_and_notify()

    def _revoke_and_notify(self):
        """Hủy các bản ghi điểm này (kể cả đã xác nhận), trả về thông báo.

        Hủy bản ghi chứ không tạo bản ghi âm, vì số dư tài khoản chỉ cộng các
        bản ghi `confirmed`: hủy là đủ để rút điểm khỏi số dư, đồng thời mở lại
        trần chống trùng điểm xếp hạng trong `stock.picking._loyalty_earn_points`
        để tích lại được cho đúng tài khoản. Bản ghi âm chỉ dùng cho hoàn hàng —
        ở đó hàng đã giao thật nên cần giữ vết cả chiều cộng lẫn chiều trừ.
        """
        ranking_revoked = sum(
            self.filtered(lambda h: h.point_type == 'ranking').mapped('point_amount')
        )
        exchange_revoked = sum(
            self.filtered(lambda h: h.point_type == 'exchange').mapped('point_amount')
        )

        # Model này không kế thừa mail.thread nên không có chatter lưu vết —
        # ghi người thu hồi vào mô tả để còn đối soát sau.
        user_name = self.env.user.name
        for history in self:
            history.write({
                'state': 'cancelled',
                'cancel_reason': 'revoke',
                'description': f'{history.description or ""} [Thu hồi bởi {user_name}]',
            })

        for picking in self.filtered(lambda h: h.point_type == 'ranking').picking_id:
            picking.sudo().loyalty_points_earned = self._get_picking_ranking_total(picking)

        parts = []
        if ranking_revoked:
            parts.append(f'{ranking_revoked:,} điểm xếp hạng')
        if exchange_revoked:
            parts.append(f'{exchange_revoked:,} điểm đổi thưởng')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thu hồi điểm Loyalty',
                'message': (
                    f'Đã thu hồi {" và ".join(parts) if parts else "0 điểm"} '
                    f'qua {len(self)} bản ghi.'
                ),
                'sticky': False,
                'type': 'success',
            },
        }

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
