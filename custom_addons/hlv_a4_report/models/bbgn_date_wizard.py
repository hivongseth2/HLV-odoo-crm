from odoo import models, fields

class BbgnDateWizard(models.TransientModel):
    _name = 'bbgn.date.wizard'
    _description = 'Chọn ngày đơn đặt hàng cho BBGN'

    picking_id = fields.Many2one('stock.picking', required=True, string='Phiếu giao nhận')
    order_date = fields.Date(string='Ngày đơn đặt hàng', required=True, default=fields.Date.context_today)

    def action_print(self):
        self.ensure_one()
        # Date field đôi khi là string 'YYYY-MM-DD', chuyển sang date rồi format an toàn:
        dt = fields.Date.to_date(self.order_date) if self.order_date else None
        order_date_str = dt.strftime('%d/%m/%Y') if dt else ''

        action = self.env.ref('hlv_a4_report.bbgn_a4_khong_gia').sudo().report_action(
            self.picking_id,
            data={'bbgn_order_date': order_date_str},   # ƯU TIÊN đọc từ data trong QWeb
            config=False
        )
        # Dự phòng: nhét vào context nữa (nếu môi trường không bơm 'data' vào template)
        action['context'] = dict(self.env.context, bbgn_order_date=order_date_str)
        return action
