from odoo import models, api, _
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _check_warehouse_permission(self, permission_field, action_name):
        """Helper kiểm tra phân quyền kho cho user hiện tại."""
        Permission = self.env['warehouse.user.permission']
        for picking in self:
            warehouse = picking.picking_type_id.warehouse_id
            if warehouse and not Permission.check_permission(
                    self.env.user, warehouse, permission_field):
                raise UserError(_(
                    'Bạn không có quyền %(action)s tại kho "%(warehouse)s".\n'
                    'Vui lòng liên hệ quản trị viên.',
                    action=action_name,
                    warehouse=warehouse.name,
                ))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.su:
            records._check_warehouse_permission(
                'can_create_transfer', _('tạo phiếu chuyển kho'))
        return records

    def button_validate(self):
        if not self.env.su:
            self._check_warehouse_permission(
                'can_confirm_picking', _('xác nhận phiếu'))
        return super().button_validate()

    def action_assign(self):
        if not self.env.su:
            self._check_warehouse_permission(
                'can_operate_picking', _('xử lý phiếu'))
        return super().action_assign()

    def action_cancel(self):
        if not self.env.su:
            self._check_warehouse_permission(
                'can_operate_picking', _('hủy phiếu'))
        return super().action_cancel()

    def do_unreserve(self):
        if not self.env.su:
            self._check_warehouse_permission(
                'can_operate_picking', _('bỏ đặt trước'))
        return super().do_unreserve()
