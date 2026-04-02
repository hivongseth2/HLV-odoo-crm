from odoo import models, api, _
from odoo.exceptions import UserError

# Mapping: picking_type.sequence_code → permission field
SEQUENCE_CODE_MAP = {
    'IN': 'can_receipt',
    'OUT': 'can_delivery',
    'INT': 'can_internal',
    'PICK': 'can_pick',
    'PACK': 'can_pack',
    'STO': 'can_storage',
}

SEQUENCE_CODE_LABEL = {
    'IN': 'phiếu nhập kho',
    'OUT': 'phiếu xuất kho',
    'INT': 'phiếu chuyển nội bộ',
    'PICK': 'phiếu lấy hàng',
    'PACK': 'phiếu đóng gói',
    'STO': 'phiếu lưu kho',
}


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _get_picking_permission_field(self):
        """Trả về (permission_field, label) dựa trên picking_type sequence_code."""
        self.ensure_one()
        code = self.picking_type_id.sequence_code or ''
        perm_field = SEQUENCE_CODE_MAP.get(code)
        label = SEQUENCE_CODE_LABEL.get(code, code)
        return perm_field, label

    def _check_picking_type_permission(self):
        """Kiểm tra quyền theo loại phiếu. Return True nếu bị chặn."""
        Permission = self.env['warehouse.user.permission']
        for picking in self:
            perm_field, label = picking._get_picking_permission_field()
            if not perm_field:
                continue
            warehouse = picking.picking_type_id.warehouse_id
            if warehouse and not Permission.check_permission(
                    self.env.user, warehouse, perm_field):
                self.env['bus.bus']._sendone(
                    self.env.user.partner_id,
                    'simple_notification',
                    {
                        'title': _('Thao tác không hợp lệ'),
                        'message': _(
                            'Bạn không có quyền thao tác %(label)s tại kho "%(warehouse)s".\n'
                            'Vui lòng liên hệ quản trị viên.',
                            label=label,
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
            Permission = self.env['warehouse.user.permission']
            for picking in records:
                perm_field, label = picking._get_picking_permission_field()
                if not perm_field:
                    continue
                warehouse = picking.picking_type_id.warehouse_id
                if warehouse and not Permission.check_permission(
                        self.env.user, warehouse, perm_field):
                    raise UserError(_(
                        'Bạn không có quyền tạo %(label)s tại kho "%(warehouse)s".\n'
                        'Vui lòng liên hệ quản trị viên.',
                        label=label,
                        warehouse=warehouse.name,
                    ))
        return records

    def button_validate(self):
        if not self.env.su:
            if self._check_picking_type_permission():
                return True
        return super().button_validate()

    def action_assign(self):
        if not self.env.su:
            if self._check_picking_type_permission():
                return True
        return super().action_assign()

    def action_cancel(self):
        if not self.env.su:
            if self._check_picking_type_permission():
                return True
        return super().action_cancel()

    def do_unreserve(self):
        if not self.env.su:
            if self._check_picking_type_permission():
                return True
        return super().do_unreserve()
