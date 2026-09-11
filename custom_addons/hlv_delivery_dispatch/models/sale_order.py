from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    x_delivery_point_id = fields.Many2one(
        related='partner_id.x_delivery_point_id', string='Điểm giao', store=True, index=True,
    )
    x_trip_stop_id = fields.Many2one(
        'hlv.delivery.trip.stop', string='Điểm trong chuyến',
        compute='_compute_trip_info', store=True, index=True,
    )
    x_trip_id = fields.Many2one(
        'hlv.delivery.trip', string='Chuyến', compute='_compute_trip_info',
        store=True, index=True,
    )
    x_registration_ids = fields.One2many(
        'hlv.delivery.trip.registration', 'sale_order_id', string='Đăng ký chuyến',
    )
    # Quan hệ ngược của trip.stop.sale_order_ids — khai ra để compute bên dưới bắt được
    # cả trường hợp điều phối tự kéo đơn vào điểm mà không qua đăng ký của sale.
    x_trip_stop_ids = fields.Many2many(
        'hlv.delivery.trip.stop', 'hlv_trip_stop_sale_order_rel', 'order_id', 'stop_id',
        string='Các điểm đã xếp',
    )
    # Cố tình KHÔNG store: danh sách khách cần thủ tục nằm ở hlv.delivery.procedure.partner
    # và được đọc qua ormcache. Nếu store, thêm/bớt một khách trong danh sách đó sẽ không
    # làm các đơn cũ tính lại, và cờ chặn sẽ sai âm thầm. Tính lại mỗi lần đọc rất rẻ.
    x_delivery_blocked = fields.Boolean(
        string='Bị chặn giao', compute='_compute_delivery_block',
    )
    x_delivery_block_reason = fields.Char(
        string='Lý do chặn', compute='_compute_delivery_block',
    )

    @api.depends('partner_id', 'x_plan_procedure_done',
                 'x_delivery_point_id.profile_ids.delivery_method')
    def _compute_delivery_block(self):
        """Đơn nào không được lên xe.

        Hai lý do khác hẳn nhau, và nguồn cũng khác nhau:

        1. Chờ thủ tục — theo TỪNG ĐƠN. Khách nào cần thủ tục nằm ở
           hlv.delivery.procedure.partner (module hlv_sale_delivery_planning), còn đã
           xong hay chưa là ô tick x_plan_procedure_done trên chính đơn đó. Cùng một
           khách, đơn này sale đã làm xong thủ tục, đơn kia chưa — nên không thể suy từ
           điểm giao.
        2. Khách không nhận giao bằng xe công ty (tự ghé lấy / CPN / Grab) — cái này mới
           là thói quen cố định của điểm.

        Phát hiện sớm thì tài xế lấp bằng điểm khác thay vì chạy không — đây là thứ đã
        cứu được một chuyến khi đối chiếu kế hoạch với thực tế.
        """
        method_labels = {
            'pickup': 'Khách tự ghé lấy — không xếp xe',
            'express': 'Gửi chuyển phát nhanh — không xếp xe',
            'grab': 'Book Grab — không xếp xe',
        }
        Procedure = self.env['hlv.delivery.procedure.partner'].sudo()
        for order in self:
            reason = False
            if Procedure.order_requires_procedure(order) and not order.x_plan_procedure_done:
                reason = 'Chờ sale hoàn tất thủ tục trước khi giao'
            if not reason:
                profile = order.x_delivery_point_id.profile_ids[:1]
                if profile:
                    reason = method_labels.get(profile.delivery_method)
            order.x_delivery_block_reason = reason or False
            order.x_delivery_blocked = bool(reason)

    @api.depends('x_trip_stop_ids', 'x_trip_stop_ids.trip_id.state')
    def _compute_trip_info(self):
        """Chuyến hiện tại của đơn, suy từ điểm đã xếp (bỏ qua chuyến đã huỷ)."""
        for order in self:
            stop = order.x_trip_stop_ids.filtered(
                lambda s: s.trip_id.state != 'cancelled'
            ).sorted('id')[-1:]
            order.x_trip_stop_id = stop.id if stop else False
            order.x_trip_id = stop.trip_id.id if stop else False
