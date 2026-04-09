import logging

from odoo import models, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

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
        # FIX: Sanitize move.line locations trước khi validate
        # JS barcode có thể ghi sai location_id (stale currentLocation)
        self._hlv_sanitize_move_line_locations()
        return super().button_validate()

    def _hlv_sanitize_move_line_locations(self):
        """Trước validate, kiểm tra move.line.location_id phải là con
        của picking.location_id. Nếu không → reset về picking header.
        Tương tự cho location_dest_id.
        Ngăn bug JS barcode ghi stale location gây self-transfer hoặc wrong-src.
        """
        for picking in self:
            if not picking.move_line_ids:
                continue
            header_src_id = picking.location_id.id
            header_dst_id = picking.location_dest_id.id
            for ml in picking.move_line_ids:
                vals = {}
                # Kiểm tra source location
                if ml.location_id.id != header_src_id:
                    pp = getattr(ml.location_id, 'parent_path', '') or ''
                    if f'/{header_src_id}/' not in pp:
                        _logger.warning(
                            'HLV Sanitize: %s line %s [%s] wrong src %s '
                            '(not child of %s) -> reset to header',
                            picking.name, ml.id,
                            ml.product_id.default_code or ml.product_id.display_name,
                            ml.location_id.complete_name,
                            picking.location_id.complete_name,
                        )
                        vals['location_id'] = header_src_id

                # Kiểm tra dest location
                if ml.location_dest_id.id != header_dst_id:
                    pp = getattr(ml.location_dest_id, 'parent_path', '') or ''
                    if f'/{header_dst_id}/' not in pp:
                        _logger.warning(
                            'HLV Sanitize: %s line %s [%s] wrong dst %s '
                            '(not child of %s) -> reset to header',
                            picking.name, ml.id,
                            ml.product_id.default_code or ml.product_id.display_name,
                            ml.location_dest_id.complete_name,
                            picking.location_dest_id.complete_name,
                        )
                        vals['location_dest_id'] = header_dst_id

                if vals:
                    ml.write(vals)

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

    # ── FIX: Backorder sanitize move.line locations sai ──────────────────
    def _create_backorder(self, backorder_moves=None):
        """Override: sau khi tạo backorder, sanitize move.line locations.
        Backorder kế thừa move.line từ phiếu gốc - nếu line có location
        không hợp lệ (do JS barcode ghi sai trước đó), reset về header.
        KHÔNG unreserve toàn phiếu - chỉ sửa location sai.
        """
        backorders = super()._create_backorder(backorder_moves=backorder_moves)
        for bo in backorders:
            self._hlv_sanitize_move_line_locations_for(bo)
        return backorders

    def _hlv_sanitize_move_line_locations_for(self, picking):
        """Kiểm tra move.line locations của 1 picking.
        Nếu location_id không phải con của picking header → reset về header.
        Giữ nguyên reservation nếu location hợp lệ.
        """
        header_src_id = picking.location_id.id
        header_dst_id = picking.location_dest_id.id
        for ml in picking.move_line_ids:
            vals = {}
            if ml.location_id.id != header_src_id:
                pp = getattr(ml.location_id, 'parent_path', '') or ''
                if f'/{header_src_id}/' not in pp:
                    _logger.warning(
                        'HLV Backorder sanitize: %s line %s [%s] wrong src %s -> reset to %s',
                        picking.name, ml.id,
                        ml.product_id.default_code or ml.product_id.display_name,
                        ml.location_id.complete_name,
                        picking.location_id.complete_name,
                    )
                    vals['location_id'] = header_src_id
            if ml.location_dest_id.id != header_dst_id:
                pp = getattr(ml.location_dest_id, 'parent_path', '') or ''
                if f'/{header_dst_id}/' not in pp:
                    vals['location_dest_id'] = header_dst_id
            if vals:
                ml.write(vals)
