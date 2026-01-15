from odoo import models, fields, api

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_open_label_wizard(self):
        self.ensure_one()
        # Tạo dòng dữ liệu cho wizard dựa trên các dòng trong phiếu kho
        wizard_lines = []
        for line in self.move_ids_without_package:
            # Mặc định lấy số lượng hoàn tất (quantity), nếu = 0 thì lấy nhu cầu
            qty = line.quantity if line.quantity > 0 else line.product_uom_qty
            if qty > 0:
                wizard_lines.append((0, 0, {
                    'product_id': line.product_id.id,
                    'qty_to_print': int(qty), # Mặc định số lượng in = số lượng thực tế
                }))

        return {
            'name': 'In Tem Sản Phẩm',
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'stock.picking.label.wizard',
            'target': 'new',
            'context': {'default_picking_id': self.id, 'default_line_ids': wizard_lines},
        }