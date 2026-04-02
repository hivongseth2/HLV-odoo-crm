from odoo import models, api, _


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _check_warehouse_permission(self, permission_field, action_name):
        """Helper kiểm tra phân quyền kho cho user hiện tại."""
        Permission = self.env['warehouse.user.permission']
        for picking in self:
            warehouse = picking.picking_type_id.warehouse_id
            if warehouse and not Permission.check_permission(
                    self.env.user, warehouse, permission_field):
                self.env['bus.bus']._sendone(
                    self.env.user.partner_id,
                    'simple_notification',
                    {
                        'title': _('Thao tác không hợp lệ'),
                        'message': _(
                            'Bạn không có quyền %(action)s tại kho "%(warehouse)s".\n'
                            'Vui lòng liên hệ quản trị viên.',
                            action=action_name,
                            warehouse=warehouse.name,
                        ),
                        'type': 'warning',
                        'sticky': True,
                    },
                )
                return True  # blocked
        return False  # allowed

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.su:
            if records._check_warehouse_permission(
                    'can_create_transfer', _('tạo phiếu chuyển kho')):
                records.unlink()
                return self.env['stock.picking']
        return records

    def button_validate(self):
        if not self.env.su:
            if self._check_warehouse_permission(
                    'can_confirm_picking', _('xác nhận phiếu')):
                return True
        return super().button_validate()

    def action_assign(self):
        if not self.env.su:
            if self._check_warehouse_permission(
                    'can_operate_picking', _('xử lý phiếu')):
                return True
        return super().action_assign()

    def action_cancel(self):
        if not self.env.su:
            if self._check_warehouse_permission(
                    'can_operate_picking', _('hủy phiếu')):
                return True
        return super().action_cancel()

    def do_unreserve(self):
        if not self.env.su:
            if self._check_warehouse_permission(
                    'can_operate_picking', _('bỏ đặt trước')):
                return True
        return super().do_unreserve()
