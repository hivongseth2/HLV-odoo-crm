from odoo import models, fields, api

class GeocodePickerWizard(models.TransientModel):
    _name = 'geocode.picker.wizard'
    _description = 'Map Geocode Picker'
    def _register_hook(self):
        self.env.cr.execute("""
            CREATE TABLE IF NOT EXISTS geocode_picker_wizard (
                id SERIAL PRIMARY KEY
            )
        """)
        return super()._register_hook()

    location_id = fields.Many2one('res.partner.delivery.location', required=True)
    address = fields.Char(string='Địa chỉ', readonly=True)
    latitude = fields.Float(string='Vĩ độ', digits=(10, 7))
    longitude = fields.Float(string='Kinh độ', digits=(10, 7))
    map_view = fields.Char(string='Bản đồ')

    def action_save(self):
        self.ensure_one()
        if self.location_id:
            self.location_id.write({
                'latitude': self.latitude,
                'longitude': self.longitude,
            })
        return {'type': 'ir.actions.act_window_close'}
