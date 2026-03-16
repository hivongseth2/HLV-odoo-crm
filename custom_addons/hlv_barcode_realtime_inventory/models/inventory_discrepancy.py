# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class InventoryDiscrepancy(models.Model):
    """
    Model lưu trữ lý do chênh lệch trong kiểm kê
    """
    _name = 'inventory.discrepancy'
    _description = 'Ghi Nhận Chênh Lệch Kiểm Kê'
    _order = 'create_date desc'

    # ========== Relationships ==========
    check_id = fields.Many2one(
        'inventory.check',
        string='Phiên Kiểm Kê',
        required=True,
        ondelete='cascade',
        index=True
    )

    line_id = fields.Many2one(
        'inventory.check.line',
        string='Dòng Kiểm Kê',
        required=True,
        ondelete='cascade'
    )

    product_id = fields.Many2one(
        'product.product',
        string='Sản Phẩm',
        related='line_id.product_id',
        store=True
    )

    # ========== Discrepancy Info ==========
    difference = fields.Float(
        string='Số Lượng Chênh Lệch',
        required=True,
        help='Chênh lệch = Thực tế - Lý thuyết'
    )

    reason = fields.Selection(
        [
            ('kiem_ton', 'Kiểm tồn'),
            ('damaged', 'Hỏng/Mất'),
            ('expired', 'Hết hạn/Cũ'),
            ('unknown_location', 'Không tìm thấy'),
            ('counting_error', 'Lỗi đếm'),
            ('recording_error', 'Lỗi ghi chép'),
            ('theft', 'Mất cắp'),
            ('other', 'Khác'),
        ],
        string='Lý Do Chênh Lệch',
        required=True
    )

    notes = fields.Text(
        string='Ghi Chú Chi Tiết',
        help='Mô tả chi tiết về nguyên nhân chênh lệch'
    )

    # ========== Status ==========
    state = fields.Selection(
        [
            ('draft', 'Nháp'),
            ('confirmed', 'Đã Xác Nhận'),
            ('expired', 'Hết Hạn'),
        ],
        string='Trạng Thái',
        default='draft',
        tracking=True
    )

    # ========== Responsible ==========
    responsible_user = fields.Many2one(
        'res.users',
        string='Người Chịu Trách Nhiệm',
        help='Người phụ trách xử lý chênh lệch'
    )

    # ========== Audit ==========
    created_by = fields.Many2one(
        'res.users',
        string='Ghi Nhận Bởi',
        default=lambda self: self.env.user,
        readonly=True
    )

    acknowledged_by = fields.Many2one(
        'res.users',
        string='Xác Nhận Bởi',
        readonly=True
    )

    acknowledged_at = fields.Datetime(
        string='Xác Nhận Lúc',
        readonly=True
    )

    # ========== Related Fields ==========
    scanned_qty = fields.Float(
        string='Số Lượng Thực Tế',
        related='line_id.scanned_qty',
        store=True
    )

    theoretical_qty = fields.Float(
        string='Số Lượng Lý Thuyết',
        related='line_id.theoretical_qty',
        store=True
    )

    location_id = fields.Many2one(
        string='Vị Trí',
        related='line_id.location_id',
        store=True
    )

    # ========== Computed Fields ==========
    check_state = fields.Selection(
        related='check_id.state',
        string='Trạng Thái Kiểm Kê',
        store=True
    )

    # ========== Actions ==========
    def action_acknowledge(self):
        """Xác nhận ghi nhận chênh lệch"""
        for record in self:
            if record.state != 'draft':
                raise ValidationError(_('Chỉ có thể xác nhận ghi nhận ở trạng thái Nháp'))
            
            if not record.reason:
                raise ValidationError(_('Vui lòng chọn lý do chênh lệch'))
            
            record.write({
                'state': 'confirmed',
                'acknowledged_by': self.env.user.id,
                'acknowledged_at': fields.Datetime.now(),
            })

    def action_reset(self):
        """Đặt lại về Nháp"""
        for record in self:
            record.write({
                'state': 'draft',
                'acknowledged_by': False,
                'acknowledged_at': False,
            })

    # ========== Constraints ==========
    @api.constrains('difference', 'reason')
    def _check_required_fields(self):
        """Đảm bảo bắt buộc điền lý do nếu có chênh lệch"""
        for record in self:
            if record.difference != 0 and not record.reason:
                raise ValidationError(
                    _('Vui lòng chọn lý do chênh lệch cho sản phẩm %s')
                    % record.product_id.name
                )

    # ========== Helper Methods ==========
    def get_discrepancy_summary(self):
        """Trả về tóm tắt thông tin chênh lệch"""
        self.ensure_one()
        return {
            'id': self.id,
            'product_name': self.product_id.display_name,
            'product_code': self.product_id.default_code,
            'difference': self.difference,
            'reason': self.reason,
            'reason_label': self._fields['reason'].selection_label(self.reason),
            'notes': self.notes,
            'state': self.state,
        }
