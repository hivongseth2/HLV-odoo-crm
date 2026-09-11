from odoo import fields, models


class HlvDeliveryPlannerSnapshot(models.Model):
    """Thêm điểm giao và cụm vào snapshot có sẵn.

    Chỉ dùng related store — KHÔNG sửa upsert_from_status_data của
    hlv_sale_delivery_planning. Nhờ vậy màn xếp chuyến lọc được theo cụm mà không phải
    join ngược qua res.partner mỗi lần.
    """

    _inherit = 'hlv.delivery.planner.snapshot'

    point_id = fields.Many2one(
        related='partner_id.x_delivery_point_id', store=True, index=True, string='Điểm giao',
    )
    zone_id = fields.Many2one(
        related='partner_id.x_delivery_point_id.zone_id', store=True, index=True,
        string='Cụm tuyến',
    )
