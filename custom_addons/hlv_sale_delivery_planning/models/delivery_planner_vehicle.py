# -*- coding: utf-8 -*-
"""Cấu hình đội xe giao hàng dùng cho AI Dispatcher.

Mỗi record = 1 chiếc xe khả dụng. AI sẽ đọc qua tool ``dp_fleet`` và
phân chuyến cho phù hợp với loại / sức chứa.
"""
from odoo import api, fields, models


class HlvDeliveryVehicle(models.Model):
    _name = 'hlv.delivery.planner.vehicle'
    _description = 'HLV Delivery Planner — Đội xe'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    name = fields.Char(string='Tên xe', required=True,
                       help='Vd: "Van 1 tấn #1", "Xe máy SH 150"')
    vehicle_type = fields.Selection([
        ('motorbike', 'Xe máy'),
        ('sedan', 'Xe ô tô con (4-7 chỗ)'),
        ('van', 'Xe van / tải nhỏ (≤1.5 tấn)'),
        ('truck', 'Xe tải lớn (≥2 tấn)'),
        ('other', 'Khác'),
    ], string='Loại xe', required=True, default='van')
    capacity_kg = fields.Float(
        string='Tải trọng (kg)', default=0.0,
        help='Khả năng chở tối đa (kg). 0 = không giới hạn.',
    )
    capacity_volume = fields.Char(
        string='Sức chứa (mô tả)', default='',
        help='Vd: "1 m³", "khoang sau đầy đủ thùng carton".',
    )
    max_orders_per_trip = fields.Integer(
        string='Số đơn / chuyến (đề xuất)', default=10,
        help='Gợi ý số đơn tối đa / chuyến. AI dùng để chia chuyến.',
    )
    preferred_for = fields.Char(
        string='Ưu tiên cho tuyến / loại đơn', default='',
        help='Vd: "Đơn nhẹ <30kg, gần kho", "Đơn lớn KCN xa".',
    )
    notes = fields.Text(string='Ghi chú thêm')
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Kho gốc',
        help='Kho mà xe này thường xuất phát. Để trống = mọi kho.',
    )
    user_id = fields.Many2one(
        'res.users', string='Tài xế cố định',
        help='Shipper mặc định nếu có. Chỉ là gợi ý, không khoá.',
    )

    @api.model
    def get_active_fleet(self, warehouse_id=None):
        """Helper trả về list dict các xe khả dụng (cho LLM tool)."""
        domain = [('active', '=', True)]
        if warehouse_id:
            domain += ['|',
                       ('warehouse_id', '=', int(warehouse_id)),
                       ('warehouse_id', '=', False)]
        out = []
        for v in self.sudo().search(domain):
            out.append({
                'id': v.id,
                'name': v.name,
                'type': dict(self._fields['vehicle_type'].selection).get(
                    v.vehicle_type, v.vehicle_type),
                'type_code': v.vehicle_type,
                'capacity_kg': v.capacity_kg,
                'capacity_volume': v.capacity_volume or '',
                'max_orders_per_trip': v.max_orders_per_trip,
                'preferred_for': v.preferred_for or '',
                'driver': v.user_id.name if v.user_id else '',
                'warehouse': v.warehouse_id.name if v.warehouse_id else '',
                'notes': v.notes or '',
            })
        return out
