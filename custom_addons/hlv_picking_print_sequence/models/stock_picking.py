from odoo import models, fields, api
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from datetime import datetime


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    print_sequence = fields.Integer(
        string='Thứ tự in',
        default=0,
        help='Số thứ tự in biên bản đi. Thấp nhất in trước'
    )
    
    print_sequence_note = fields.Char(
        string='Ghi chú sắp xếp',
        help='Ghi chú về thứ tự sắp xếp in'
    )

    @api.model
    def get_print_sequence_wizard_action(self):
        """Mở wizard sắp xếp thứ tự in"""
        action = self.env['ir.actions.act_window']._for_xml_id(
            'hlv_picking_print_sequence.action_picking_print_sequence_wizard'
        )
        return action

    def action_auto_sequence(self):
        """Tự động đánh số thứ tự theo ngày tạo (cũ trước, mới sau)"""
        pickings = self.search([
            ('state', 'in', ['waiting', 'confirmed', 'assigned']),
            ('picking_type_id.code', 'in', ['outgoing', 'internal'])
        ], order='create_date asc')
        
        for idx, picking in enumerate(pickings, 1):
            picking.print_sequence = idx
            
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thành công',
                'message': f'Đã đánh số thứ tự cho {len(pickings)} biên bản đi',
                'type': 'success',
                'sticky': False,
            }
        }

    def action_reset_sequence(self):
        """Xóa thứ tự in (reset về 0)"""
        self.write({'print_sequence': 0, 'print_sequence_note': ''})
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thành công',
                'message': f'Đã xóa thứ tự in của {len(self)} biên bản đi',
                'type': 'success',
                'sticky': False,
            }
        }

    def action_print_by_sequence(self):
        """In biên bản đi theo thứ tự đã sắp xếp"""
        # Lọc những phiếu đã gán sequence
        pickings_with_seq = self.filtered(lambda p: p.print_sequence > 0).sorted(
            key=lambda p: p.print_sequence
        )
        
        if not pickings_with_seq:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Lỗi',
                    'message': 'Không có biên bản đi nào có thứ tự in',
                    'type': 'danger',
                    'sticky': True,
                }
            }
        
        # In từng biên bản theo thứ tự
        return {
            'type': 'ir.actions.report',
            'report_name': 'stock.report_picking',
            'report_type': 'qweb-pdf',
            'ids': pickings_with_seq.ids,
        }

    def action_print_delivery_note(self):
        """In biên bản giao nhận / biên bản đi"""
        return {
            'type': 'ir.actions.report',
            'report_name': 'hoanglongvu_delivery_note.report_delivery_note',
            'report_type': 'qweb-pdf',
            'ids': self.ids,
        }

    @api.model
    def get_sorted_pickings_for_print(self, picking_type_code='outgoing', date_from=None, date_to=None):
        """
        Lấy danh sách biên bản đi sắp xếp theo thứ tự in
        
        Args:
            picking_type_code: 'outgoing' (xuất kho), 'incoming' (nhập kho), 'internal' (chuyển nội bộ)
            date_from: Ngày bắt đầu lọc (YYYY-MM-DD)
            date_to: Ngày kết thúc lọc (YYYY-MM-DD)
        
        Returns:
            List of stock.picking records sorted by print_sequence
        """
        domain = [
            ('picking_type_id.code', '=', picking_type_code),
            ('state', 'in', ['done'])  # Chỉ lấy những phiếu đã hoàn tất
        ]
        
        if date_from:
            domain.append(('date_done', '>=', date_from))
        if date_to:
            domain.append(('date_done', '<=', date_to))
        
        pickings = self.search(domain, order='print_sequence asc, create_date asc')
        return pickings

    def _assign_print_sequence_by_date(self, start_seq=1):
        """
        Chỉ định sequence dựa trên ngày (phải tính từ ngày cũ nhất)
        Dùng trong các tình huống batch processing
        """
        sorted_pickings = self.sorted(key=lambda p: p.create_date)
        for idx, picking in enumerate(sorted_pickings, start=start_seq):
            picking.print_sequence = idx
        return True
