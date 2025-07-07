from odoo import models, fields, api
from datetime import datetime

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def print_delivery_note(self):
        """In delivery note cho picking - chỉ cho delivery orders"""
        if self.picking_type_code == 'outgoing':
            return self.env.ref('hoanglongvu_delivery_note.action_report_delivery_note').report_action(self)
        return False


class StockMove(models.Model):
    _inherit = 'stock.move'

    def print_logistic_tag_line(self):
        """In logistic tag cho từng stock move"""
        return self.env.ref('hoanglongvu_delivery_note.action_report_logistic_tag').report_action(self)
    
    def get_buyer_po_number(self):
        """Lấy số PO của buyer từ sale order"""
        if self.sale_line_id and self.sale_line_id.order_id:
            return self.sale_line_id.order_id.client_order_ref or self.sale_line_id.order_id.name
        return self.picking_id.origin or ''
    
    def get_supplier_code(self):
        """Lấy mã nhà cung cấp"""
        if hasattr(self.picking_id.partner_id, 'supplier_rank') and self.picking_id.partner_id.supplier_rank > 0:
            return self.picking_id.partner_id.ref or str(self.picking_id.partner_id.id)
        return self.picking_id.company_id.partner_id.ref or str(self.picking_id.company_id.id)

class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'
    
    def print_logistic_tag_line(self):
        """In logistic tag cho move line - chuyển đổi sang stock.move để in"""
        return self.move_id.print_logistic_tag_line()
