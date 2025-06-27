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
    @api.model
    def action_scan_barcode(self):
        # Khi quét barcode bắt đầu quay video
        self.ensure_one()
        self.video_state = 'recording'
        self.video_url = False
        # Gọi hàm thực hiện quay từ video_utils (đã viết trước)
        self.env['warehouse.video.packaging'].start_video_for_picking(self.id)

    def button_validate(self):
        # Khi xác nhận phiếu xuất thì dừng video và upload
        res = super().button_validate()
        for picking in self:
            if picking.video_state == 'recording':
                picking.env['warehouse.video.packaging'].stop_and_upload_video(picking.id)
                picking.write({'video_state': 'uploaded'})
        return res
