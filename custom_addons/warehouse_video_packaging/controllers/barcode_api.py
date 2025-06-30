# controllers/barcode_api.py
from odoo import http
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)

class WarehouseVideoAPI(http.Controller):

    @http.route(
        '/warehouse_video_packaging/api/scan',
        type='json', auth='public', methods=['POST'], csrf=False
    )
    def api_scan(self, **kwargs):
        barcode = kwargs.get('barcode')
        if not barcode:
            return {'error': 'Missing barcode'}

        Session = request.env['warehouse.video.session'].sudo()
        recording = Session.search([('state', '=', 'recording')], limit=1)

        if recording:
            recording.stop_recording()

        new_session = Session.start_recording(barcode)
        return {'result': f'Started recording for {barcode}', 'session_id': new_session.id}
