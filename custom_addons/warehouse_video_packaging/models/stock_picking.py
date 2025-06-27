from odoo import models, fields, api
from ..tools import video_utils

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    video_state = fields.Selection([
        ('idle', 'Chưa quay'),
        ('recording', 'Đang quay'),
        ('uploaded', 'Đã upload'),
    ], string="Trạng thái video", default="idle")

    video_file_name = fields.Char("Tên file video")
    video_url = fields.Char("Link video Drive")

    _video_process = None

    def action_put_in_pack(self):
        res = super().action_put_in_pack()
        for picking in self:
            if picking.video_state == 'idle':
                picking.video_state = 'recording'
                picking.video_file_name = f"{picking.name}.mp4"
                proc, output = video_utils.start_recording(picking.name)
                picking._video_process = proc
                picking.video_url = output
        return res

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            if picking.video_state == 'recording':
                video_utils.stop_process(picking._video_process)
                video_utils.upload_async(picking.video_url)
                picking.write({'video_state': 'uploaded'})
        return res
