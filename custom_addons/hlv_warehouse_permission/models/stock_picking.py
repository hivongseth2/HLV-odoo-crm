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

# Đổi các field này là đổi phiếu sang kho khác -> phải kiểm lại quyền.
LOCATION_FIELDS = {'picking_type_id', 'location_id', 'location_dest_id'}


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _touched_warehouses(self):
        """Mọi kho mà phiếu thực sự đụng tới.

        Không chỉ lấy kho của loại hoạt động: người dùng có thể chọn loại "Bến Cam:
        Nhập kho" nhưng đặt vị trí đích (trên phiếu hoặc từng dòng chi tiết) ở kho
        Tân Sơn Nhì, và hàng thật sự vào Tân Sơn Nhì.
        """
        self.ensure_one()
        locations = (
            self.location_id | self.location_dest_id
            | self.move_ids.location_id | self.move_ids.location_dest_id
            | self.move_line_ids.location_id | self.move_line_ids.location_dest_id
        )
        return self.picking_type_id.warehouse_id | locations.warehouse_id

    def _find_blocked_operation(self, operation_field):
        """Trả về (nhãn loại phiếu, kho bị chặn) đầu tiên, hoặc None nếu được phép."""
        Permission = self.env['warehouse.user.permission']
        for picking in self:
            code = picking.picking_type_id.sequence_code or ''
            if code not in SEQUENCE_CODE_LABEL:
                continue
            for warehouse in picking._touched_warehouses():
                if not Permission.check_picking_operation(
                        self.env.user, warehouse, code, operation_field):
                    return SEQUENCE_CODE_LABEL[code], warehouse
        return None

    def _raise_if_blocked(self, operation_field, operation_label):
        if self.env.su:
            return
        blocked = self._find_blocked_operation(operation_field)
        if blocked:
            label, warehouse = blocked
            raise UserError(_(
                'Bạn không có quyền %(operation)s %(label)s tại kho "%(warehouse)s".\n'
                'Vui lòng liên hệ quản trị viên.',
                operation=operation_label,
                label=label,
                warehouse=warehouse.name,
            ))

    def _check_picking_operation(self, operation_field, operation_label):
        """Gửi toast nếu bị chặn (không raise để không văng lỗi giữa luồng nút bấm).

        Trả về True nếu bị chặn.
        """
        if self.env.su:
            return False
        blocked = self._find_blocked_operation(operation_field)
        if not blocked:
            return False
        label, warehouse = blocked
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
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._raise_if_blocked('can_create', _('tạo'))
        return records

    def write(self, vals):
        res = super().write(vals)
        if LOCATION_FIELDS & set(vals):
            self._raise_if_blocked('can_edit', _('sửa'))
        return res

    def unlink(self):
        self._raise_if_blocked('can_delete', _('xóa'))
        return super().unlink()

    def button_validate(self):
        if self._check_picking_operation('can_confirm', _('xác nhận')):
            return True
        return super().button_validate()

    def action_assign(self):
        if self._check_picking_operation('can_edit', _('xử lý')):
            return True
        return super().action_assign()

    def action_cancel(self):
        if self._check_picking_operation('can_cancel', _('hủy')):
            return True
        return super().action_cancel()

    def do_unreserve(self):
        if self._check_picking_operation('can_edit', _('bỏ đặt trước')):
            return True
        return super().do_unreserve()
