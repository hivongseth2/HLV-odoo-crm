from odoo import models, fields

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    video_state = fields.Selection([
        ('idle', 'Chưa quay'),
        ('recording', 'Đang quay'),
        ('uploaded', 'Đã upload'),
    ], string="Trạng thái video", default="idle")

    video_file_name = fields.Char("Tên file video")
    video_url = fields.Char("Link video Drive")
