from odoo import models, fields, api
from ..tools import video_utils  # ⬅️ import file tools

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    video_state = fields.Selection([
        ('idle', 'Chưa quay'),
        ('recording', 'Đang quay'),
        ('uploaded', 'Đã upload'),
    ], string="Trạng thái video", default="idle")

    video_file_name = fields.Char("Tên file video")
    video_url = fields.Char("Link video Drive")

    _video_process = None  # Biến tạm trong Python (không lưu DB)

    def action_scan_barcode(self):
        self.ensure_one()
        self.video_state = 'recording'
        self.video_file_name = f"{self.name}.mp4"

        # Gọi quay
        proc, output = video_utils.start_recording(self.name)
        self._video_process = proc
        self.video_url = output  # Hoặc chỉ lưu path tạm

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            if picking.video_state == 'recording':
                # Dừng quay
                video_utils.stop_process(picking._video_process)
                # Upload
                video_utils.upload_async(picking.video_url)
                picking.write({'video_state': 'uploaded'})
        return res
