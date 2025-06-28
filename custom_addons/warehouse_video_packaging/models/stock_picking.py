from odoo import models, fields
from ..tools import video_utils

import logging
_logger = logging.getLogger(__name__)

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
        _logger.info("🟢 GỌI action_put_in_pack() TRIGGERED >>>>>>>>>>")
        res = super().action_put_in_pack()
        for picking in self:
            if picking.video_state == 'idle':
                picking.video_state = 'recording'
                picking.video_file_name = f"{picking.name}.mp4"
                proc, output = video_utils.start_recording(picking.name)
                # picking._video_process = proc
                picking._video_process_runtime = proc
                picking.video_url = output
                _logger.info(f"🎥 BẮT ĐẦU QUAY: {output}")
            else:
                _logger.info(f"ℹ️ Phiếu {picking.name} đã ở trạng thái: {picking.video_state}")
        return res

    def button_validate(self):
        _logger.info("✅ GỌI button_validate() TRIGGERED >>>>>>>>>>")
        res = super().button_validate()
        for picking in self:
            if picking.video_state == 'recording':
                video_utils.stop_process(picking._video_process_runtime)
                video_utils.upload_async(picking.video_url)
                picking.write({'video_state': 'uploaded'})
                _logger.info(f"📤 UPLOAD FILE: {picking.video_url}")
        return res
