# models/warehouse_video_session.py
from odoo import models, fields, api
import logging
from ..tools import video_utils

_logger = logging.getLogger(__name__)

class WarehouseVideoSession(models.Model):
    _name = 'warehouse.video.session'
    _description = 'Warehouse Video Session'

    barcode = fields.Char('Barcode')
    state = fields.Selection([
        ('idle', 'Idle'),
        ('recording', 'Recording'),
        ('uploaded', 'Uploaded')
    ], default='idle')

    file_name = fields.Char('File Name')
    file_url = fields.Char('File URL')
    start_time = fields.Datetime('Start Time')
    end_time = fields.Datetime('End Time')

    # Biến tạm giữ process
    VIDEO_PROCESS = {}

    @api.model
    def start_recording(self, barcode):
        file_name = f"{barcode}.mp4"
        proc, output = video_utils.start_recording(barcode)
        session = self.create({
            'barcode': barcode,
            'state': 'recording',
            'file_name': file_name,
            'file_url': output,
            'start_time': fields.Datetime.now()
        })
        type(self).VIDEO_PROCESS[session.id] = proc
        _logger.info(f"✅ Bắt đầu quay: {output}")
        return session
    
    
    
    # chuẩn
    def start_recording_session(self):
        for rec in self:
            file_name = f"{rec.barcode}.mp4"
            proc, output = video_utils.start_recording(rec.barcode)
            rec.write({
                'state': 'recording',
                'file_name': file_name,
                'file_url': output,
                'start_time': fields.Datetime.now()
            })
            type(self).VIDEO_PROCESS[rec.id] = proc
            _logger.info(f"✅ Bắt đầu quay: {output}")


    def stop_recording(self):
        proc = type(self).VIDEO_PROCESS.get(self.id)
        if proc:
            video_utils.stop_process(proc)
            del type(self).VIDEO_PROCESS[self.id]
        video_utils.upload_async(self.file_url)
        self.write({
            'state': 'uploaded',
            'end_time': fields.Datetime.now()
        })
        _logger.info(f"⏹️ Dừng & upload: {self.file_url}")
        
        
    def start_recording_button(self):
        for rec in self:
            rec.start_recording_session()

    def stop_recording_button(self):
        for rec in self:
            rec.stop_recording()

