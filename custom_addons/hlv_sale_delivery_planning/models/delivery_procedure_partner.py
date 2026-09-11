"""Cấu hình khách hàng bắt buộc xác nhận thủ tục trước khi giao.

Chỉ một số công ty khách mới yêu cầu kho/sale xác nhận "đã hoàn tất thủ tục"
trước khi xuất hàng. Bảng này liệt kê các khách đó; đơn nào có liên hệ gốc
(commercial_partner_id) nằm trong danh sách mới hiện ô tick trên /sale_plan và
trang Điều phối Giao hàng.
"""

from odoo import api, fields, models, tools


class DeliveryProcedurePartner(models.Model):
    _name = 'hlv.delivery.procedure.partner'
    _description = 'Khách hàng cần xác nhận thủ tục trước khi giao'
    _order = 'partner_id'
    _sql_constraints = [
        ('uniq_partner', 'unique(partner_id)', 'Mỗi khách hàng chỉ được cấu hình một lần.'),
    ]

    partner_id = fields.Many2one(
        'res.partner',
        string='Khách hàng (liên hệ gốc)',
        required=True,
        index=True,
        ondelete='cascade',
        domain="[('parent_id', '=', False)]",
        help='Chọn liên hệ gốc (công ty). Mọi đơn của các liên hệ con thuộc công ty '
             'này đều phải xác nhận thủ tục trước khi giao.',
    )
    active = fields.Boolean(string='Đang áp dụng', default=True)
    note = fields.Char(string='Ghi chú', help='Thủ tục gồm những gì, ai phụ trách...')

    @api.model
    @tools.ormcache()
    def _required_partner_ids(self):
        """Id các liên hệ gốc đang bật yêu cầu xác nhận thủ tục.

        Được gọi cho từng đơn khi render dashboard nên phải cache — bảng này
        rất nhỏ và gần như không đổi. Cache được xoá ở create/write/unlink.
        """
        return tuple(self.sudo().search([]).mapped('partner_id').ids)

    @api.model
    def order_requires_procedure(self, order):
        """Đơn này có phải xác nhận thủ tục không (xét theo liên hệ gốc)."""
        root = order.partner_id.commercial_partner_id if order.partner_id else False
        return bool(root and root.id in self._required_partner_ids())

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env.registry.clear_cache()
        return records

    def write(self, vals):
        result = super().write(vals)
        self.env.registry.clear_cache()
        return result

    def unlink(self):
        result = super().unlink()
        self.env.registry.clear_cache()
        return result
