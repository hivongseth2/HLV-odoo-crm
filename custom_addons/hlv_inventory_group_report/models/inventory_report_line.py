from odoo import models, fields


class HlvInventoryReportLine(models.TransientModel):
    _name = 'hlv.inventory.report.line'
    _description = 'Dòng kết quả báo cáo tồn kho'
    _order = 'sequence, product_code'

    wizard_id = fields.Many2one('hlv.inventory.report.wizard', ondelete='cascade')
    sequence = fields.Integer(default=10)
    group_name = fields.Char('Nhóm')
    product_code = fields.Char('Mã SP')
    product_name = fields.Char('Tên sản phẩm')
    qty_details = fields.Char('Tồn theo kho/vị trí')
    qty_total = fields.Float('Tổng tồn', digits=(16, 2))
