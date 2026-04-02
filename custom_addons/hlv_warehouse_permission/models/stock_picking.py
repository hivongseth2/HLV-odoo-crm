from odoo import models, api, _
from odoo.exceptions import UserError

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

    def _check_picking_operation(self, operation_field, operation_label):
        """Check permission for a specific operation. Returns True if blocked."""
        Permission = self.env['warehouse.user.permission']
        for picking in self:
            code = picking.picking_type_id.sequence_code or ''
            if code not in SEQUENCE_CODE_LABEL:
                continue
            warehouse = picking.picking_type_id.warehouse_id
            if warehouse and not Permission.check_picking_operation(
                    self.env.user, warehouse, code, operation_field):
                label = SEQUENCE_CODE_LABEL[code]
                self.env['bus.bus']._sendone(
                    self.env.user.partner_id,
                    'simple_notification',
                    {
                        'title': _('Thao tác không hợp lệ'),
                        'message': _(
                            'Bạn không có quyền %(operation)s %(label)s tại kho "%(warehouse)s".\n'
                            'Vui lòng liên hệ quản trị viên.',
                            operation=operation_label,
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
                code = picking.picking_type_id.sequence_code or ''
                if code not in SEQUENCE_CODE_LABEL:
                    continue
                warehouse = picking.picking_type_id.warehouse_id
                if warehouse and not Permission.check_picking_operation(
                        self.env.user, warehouse, code, 'can_create'):
                    label = SEQUENCE_CODE_LABEL[code]
                    raise UserError(_(
                        'Bạn không có quyền tạo %(label)s tại kho "%(warehouse)s".\n'
                        'Vui lòng liên hệ quản trị viên.',
                        label=label,
                        warehouse=warehouse.name,
                    ))
        return records

    def unlink(self):
        if not self.env.su:
            Permission = self.env['warehouse.user.permission']
            for picking in self:
                code = picking.picking_type_id.sequence_code or ''
                if code not in SEQUENCE_CODE_LABEL:
                    continue
                warehouse = picking.picking_type_id.warehouse_id
                if warehouse and not Permission.check_picking_operation(
                        self.env.user, warehouse, code, 'can_delete'):
                    label = SEQUENCE_CODE_LABEL[code]
                    raise UserError(_(
                        'Bạn không có quyền xóa %(label)s tại kho "%(warehouse)s".\n'
                        'Vui lòng liên hệ quản trị viên.',
                        label=label,
                        warehouse=warehouse.name,
                    ))
        return super().unlink()

    def button_validate(self):
        if not self.env.su:
            if self._check_picking_operation('can_confirm', _('xác nhận')):
                return True
        return super().button_validate()

    def action_assign(self):
        if not self.env.su:
            if self._check_picking_operation('can_edit', _('xử lý')):
                return True
        return super().action_assign()

    def action_cancel(self):
        if not self.env.su:
            if self._check_picking_operation('can_cancel', _('hủy')):
                return True
        return super().action_cancel()

    def do_unreserve(self):
        if not self.env.su:
            if self._check_picking_operation('can_edit', _('bỏ đặt trước')):
                return True
        return super().do_unreserve()
