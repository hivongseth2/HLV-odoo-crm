from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PickingPrintSequenceWizard(models.TransientModel):
    _name = 'picking.print.sequence.wizard'
    _description = 'Wizard sắp xếp thứ tự in biên bản'

    sequence_method = fields.Selection([
        ('manual', 'Sắp xếp thủ công'),
        ('by_date', 'Theo ngày tạo (cũ trước)'),
        ('by_due_date', 'Theo ngày dự tính giao'),
        ('by_warehouse', 'Theo vị trí kho'),
        ('by_customer', 'Theo khách hàng (A-Z)'),
        ('by_priority', 'Theo mức ưu tiên'),
    ], default='by_date', required=True, string='Cách sắp xếp')

    picking_ids = fields.Many2many(
        'stock.picking',
        string='Phiếu kho',
        help='Để trống để sắp xếp tất cả, hoặc chọn những phiếu cụ thể'
    )

    picking_type = fields.Selection([
        ('outgoing', 'Xuất kho'),
        ('incoming', 'Nhập kho'),
        ('internal', 'Chuyển nội bộ'),
    ], default='outgoing', string='Loại phiếu')

    state_filter = fields.Selection([
        ('all', 'Tất cả'),
        ('waiting', 'Chờ...'),
        ('confirmed', 'Xác nhận'),
        ('assigned', 'Đã gán'),
        ('done', 'Hoàn tất'),
    ], default='done', string='Trạng thái phiếu')

    reset_before = fields.Boolean(
        default=True,
        string='Xóa sequence cũ trước khi sắp xếp',
        help='Nếu checked, sẽ xóa giá trị sequence cũ rồi sắp xếp lại từ đầu'
    )

    start_sequence = fields.Integer(
        default=1,
        string='Bắt đầu từ số',
        help='Số thứ tự bắt đầu (default: 1)'
    )

    dry_run = fields.Boolean(
        default=False,
        string='Chế độ xem trước (không lưu)',
        help='Nếu checked, sẽ hiển thị kết quả mà không lưu vào database'
    )

    preview_ids = fields.Many2many(
        'stock.picking',
        'wizard_picking_preview_rel',
        string='Xem trước kết quả'
    )

    @api.onchange('sequence_method')
    def _onchange_sequence_method(self):
        """Cập nhật description khi thay đổi method"""
        descriptions = {
            'manual': 'Tự bạn chọn thứ tự cho mỗi phiếu',
            'by_date': 'Phiếu cũ hơn sẽ in trước',
            'by_due_date': 'Phiếu giao sớm hơn sẽ in trước',
            'by_warehouse': 'Nhóm theo kho, mỗi kho sắp xếp riêng',
            'by_customer': 'Nhóm theo khách hàng theo thứ tự A-Z',
            'by_priority': 'Phiếu ưu tiên cao hơn sẽ in trước',
        }
        # Có thể thêm field description để hiển thị

    def action_preview(self):
        """Xem trước kết quả sắp xếp"""
        self.dry_run = True
        pickings = self._get_target_pickings()
        sorted_pickings = self._sort_pickings(pickings)
        
        self.preview_ids = sorted_pickings
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Xem trước',
                'message': f'Sẽ sắp xếp {len(sorted_pickings)} phiếu kho',
                'type': 'info',
            }
        }

    def action_apply(self):
        """Áp dụng sắp xếp"""
        pickings = self._get_target_pickings()
        
        if not pickings:
            raise ValidationError('Không có phiếu kho nào để sắp xếp. Vui lòng kiểm tra bộ lọc.')
        
        # Reset sequence cũ nếu cần
        if self.reset_before:
            pickings.write({'print_sequence': 0})
        
        # Sắp xếp
        sorted_pickings = self._sort_pickings(pickings)
        
        # Gán sequence
        for idx, picking in enumerate(sorted_pickings, self.start_sequence):
            picking.print_sequence = idx
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thành công',
                'message': f'Đã sắp xếp {len(sorted_pickings)} phiếu kho',
                'type': 'success',
                'sticky': False,
            }
        }

    def _get_target_pickings(self):
        """Lấy danh sách phiếu cần sắp xếp"""
        domain = []
        
        # Filter theo loại phiếu
        if self.picking_type:
            domain.append(('picking_type_id.code', '=', self.picking_type))
        
        # Filter theo trạng thái
        if self.state_filter == 'all':
            domain.append(('state', 'in', ['waiting', 'confirmed', 'assigned', 'done']))
        elif self.state_filter:
            domain.append(('state', '=', self.state_filter))
        
        # Nếu chọn picking cụ thể thì dùng picking đó, không thì lấy theo filter
        if self.picking_ids:
            pickings = self.picking_ids.filtered_domain(domain)
        else:
            pickings = self.env['stock.picking'].search(domain)
        
        return pickings

    def _sort_pickings(self, pickings):
        """Sắp xếp phiếu theo method đã chọn"""
        if self.sequence_method == 'manual':
            return pickings
        
        elif self.sequence_method == 'by_date':
            return pickings.sorted(key=lambda p: p.create_date)
        
        elif self.sequence_method == 'by_due_date':
            return pickings.sorted(key=lambda p: p.scheduled_date or p.create_date)
        
        elif self.sequence_method == 'by_warehouse':
            return pickings.sorted(
                key=lambda p: (p.location_dest_id.name, p.create_date)
            )
        
        elif self.sequence_method == 'by_customer':
            return pickings.sorted(
                key=lambda p: (p.partner_id.name or '', p.create_date)
            )
        
        elif self.sequence_method == 'by_priority':
            # Priority: urgent > high > normal > low
            priority_order = {'2': 0, '1': 1, '0': 2, '3': 3}
            return pickings.sorted(
                key=lambda p: (priority_order.get(p.priority, 4), p.create_date)
            )
        
        return pickings


class StockPickingAction(models.Model):
    _inherit = 'stock.picking'

    def action_open_print_sequence_wizard(self):
        """Mở wizard sắp xếp print sequence"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sắp xếp thứ tự in',
            'res_model': 'picking.print.sequence.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_picking_ids': self.ids if self.ids else [],
                'default_picking_type': self.picking_type_id.code if self else 'outgoing',
            }
        }
