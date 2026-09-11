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
    x_delivery_blocked = fields.Boolean(
        string='Bị chặn thủ tục', compute='_compute_delivery_block', store=True, index=True,
    )
    x_delivery_block_reason = fields.Char(
        string='Lý do chặn', compute='_compute_delivery_block', store=True,
    )

    @api.depends('x_delivery_point_id',
                 'x_delivery_point_id.profile_ids.procedure_before',
                 'x_delivery_point_id.profile_ids.delivery_method')
    def _compute_delivery_block(self):
        """Cột thủ tục: đơn nào không được lên xe nếu chưa xử lý trước.

        Phát hiện sớm thì tài xế lấp bằng điểm khác thay vì chạy không — đây là thứ
        đã cứu được một chuyến khi đối chiếu kế hoạch với thực tế.
        """
        labels = {
            'customs': 'Cần khai hải quan trước (khu chế xuất)',
            'register': 'Cần đăng ký trước khi giao',
        }
        method_labels = {
            'pickup': 'Khách tự ghé lấy — không xếp xe',
            'express': 'Gửi chuyển phát nhanh — không xếp xe',
            'grab': 'Book Grab — không xếp xe',
        }
        for order in self:
            profile = order.x_delivery_point_id.profile_ids[:1]
            reason = False
            if profile:
                reason = labels.get(profile.procedure_before) or method_labels.get(
                    profile.delivery_method
                )
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
