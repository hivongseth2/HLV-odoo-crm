from odoo import models, api


class HlvStockQuick(models.TransientModel):
    _name = 'hlv.stock.quick'
    _description = 'Xem ton kho theo nhom'

    @api.model
    def get_data(self, group_id, warehouse_id, show_zero):
        if not group_id:
            return {'lines': [], 'total': 0.0}
        group = self.env['hlv.product.report.group'].browse(group_id)
        lines = []
        total = 0.0
        for product in group.product_ids.sorted('default_code'):
            if warehouse_id:
                qty = product.with_context(warehouse=warehouse_id).qty_available
            else:
                qty = product.qty_available
            if not show_zero and qty == 0:
                continue
            lines.append({
                'code': product.default_code or '',
                'name': product.name,
                'qty': qty,
            })
            total += qty
        return {'lines': lines, 'total': total}
