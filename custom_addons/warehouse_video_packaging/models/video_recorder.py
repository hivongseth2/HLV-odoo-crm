
from odoo import models, fields
from ..tools.video_utils import start_recording, stop_process, upload_async

class VideoPackaging(models.Model):
    _name = 'warehouse.video.packaging'
    _description = 'Video Packaging Process'

    name = fields.Char(string="Barcode")
    video_path = fields.Char(string="Video Path")
    state = fields.Selection([
        ('recording', 'Recording'),
        ('done', 'Done')
    ], default='recording')

    def action_start_record(self):
        for record in self:
            proc, path = start_recording(record.name)
            record.video_path = path
            record.env.context = dict(record.env.context, _video_proc=proc)

    def action_stop_record(self):
        for record in self:
            proc = self.env.context.get('_video_proc')
            stop_process(proc)
            upload_async(record.video_path)
            record.state = 'done'
