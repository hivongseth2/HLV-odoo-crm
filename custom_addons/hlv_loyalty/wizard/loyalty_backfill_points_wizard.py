# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class HlvLoyaltyBackfillPointsWizard(models.TransientModel):
    _name = 'hlv.loyalty.backfill.points.wizard'
    _description = 'Wizard tạo bù điểm Loyalty'

    POINT_TYPES_BY_SCOPE = {
        'all': ['ranking', 'exchange'],
        'ranking': ['ranking'],
        'exchange': ['exchange'],
    }

    order_id = fields.Many2one(
        'sale.order', string='Đơn bán hàng', required=True, readonly=True,
    )
    point_scope = fields.Selection([
        ('all', 'Cả 2 loại điểm'),
        ('ranking', 'Chỉ điểm xếp hạng'),
        ('exchange', 'Chỉ điểm đổi thưởng'),
    ], string='Loại điểm cần bù', required=True, default='all')

    preview_ranking = fields.Integer(
        string='Điểm xếp hạng sẽ bù', compute='_compute_preview', readonly=True,
    )
    preview_exchange = fields.Integer(
        string='Điểm đổi thưởng sẽ bù', compute='_compute_preview', readonly=True,
    )
    preview_detail = fields.Html(
        string='Chi tiết', compute='_compute_preview', readonly=True, sanitize=False,
    )

    @api.depends('order_id', 'point_scope')
    def _compute_preview(self):
        for wizard in self:
            if not wizard.order_id or not wizard.point_scope:
                wizard.preview_ranking = 0
                wizard.preview_exchange = 0
                wizard.preview_detail = ''
                continue
            point_types = self.POINT_TYPES_BY_SCOPE[wizard.point_scope]
            rows, ranking_total, exchange_total = wizard._collect_backfill_rows(point_types)
            wizard.preview_ranking = ranking_total
            wizard.preview_exchange = exchange_total
            wizard.preview_detail = wizard._render_preview_table(rows)

    def _collect_backfill_rows(self, point_types):
        """Gom số điểm SẼ được tạo bù trên từng phiếu/tài khoản của đơn.

        Nhận: danh sách loại điểm ('ranking' / 'exchange').
        Trả: (rows, tổng điểm xếp hạng, tổng điểm đổi thưởng) — `rows` là list
        dict {picking, account, ranking, exchange}, chỉ chứa dòng thực sự có
        điểm để bù; rỗng nếu không có gì để bù.
        """
        self.ensure_one()
        rows = []
        ranking_total = 0
        exchange_total = 0
        for picking in self.order_id._get_loyalty_backfill_pickings():
            for item in picking._get_loyalty_earn_plan(point_types):
                ranking = item['ranking_to_create']
                exchange = 0 if item['skip_exchange'] else item['exchange_to_create']
                if not ranking and not exchange:
                    continue
                rows.append({
                    'picking': picking.name,
                    'account': item['account'].display_name,
                    'ranking': ranking,
                    'exchange': exchange,
                })
                ranking_total += ranking
                exchange_total += exchange
        return rows, ranking_total, exchange_total

    def _render_preview_table(self, rows):
        """Dựng bảng HTML xem trước từ `rows` của `_collect_backfill_rows`."""
        if not rows:
            return (
                '<p class="text-muted mb-0">Không có điểm nào cần tạo bù — '
                'dữ liệu đã đầy đủ, hoặc đơn chưa đủ điều kiện tích điểm.</p>'
            )
        body = ''.join(
            '<tr>'
            f'<td>{row["picking"]}</td>'
            f'<td>{row["account"]}</td>'
            f'<td class="text-end">{row["ranking"]:,}</td>'
            f'<td class="text-end">{row["exchange"]:,}</td>'
            '</tr>'
            for row in rows
        )
        return (
            '<div class="table-responsive">'
            '<table class="table table-sm table-bordered mb-0">'
            '<thead><tr>'
            '<th>Phiếu kho</th><th>Tài khoản Loyalty</th>'
            '<th class="text-end">Điểm xếp hạng</th>'
            '<th class="text-end">Điểm đổi thưởng</th>'
            '</tr></thead>'
            f'<tbody>{body}</tbody>'
            '</table></div>'
        )

    def action_confirm_backfill(self):
        self.ensure_one()
        if not self.preview_ranking and not self.preview_exchange:
            raise UserError(
                'Không có điểm nào để tạo bù với lựa chọn hiện tại. '
                'Hãy đổi loại điểm hoặc kiểm tra lại bảng "Tài khoản cộng điểm Loyalty" trên đơn.'
            )
        return self.order_id._backfill_loyalty_points(
            self.POINT_TYPES_BY_SCOPE[self.point_scope]
        )
