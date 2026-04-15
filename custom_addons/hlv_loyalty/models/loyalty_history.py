# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class LoyaltyHistory(models.Model):
    _name = 'loyalty.history'
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
        ('redeem', 'Đổi Voucher'),
        ('return', 'Hoàn hàng'),
        ('manual', 'Điều chỉnh thủ công'),
    ], string='Loại giao dịch', required=True, index=True)

    description = fields.Char(string='Mô tả')

    # Tham chiếu chéo
    picking_id = fields.Many2one('stock.picking', string='Phiếu kho', readonly=True)
    sale_order_id = fields.Many2one('sale.order', string='Đơn bán hàng', readonly=True)
    voucher_id = fields.Many2one('loyalty.voucher', string='Voucher', readonly=True)

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
