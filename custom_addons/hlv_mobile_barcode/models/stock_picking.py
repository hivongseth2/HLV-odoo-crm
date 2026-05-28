from odoo import models, fields

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    second_transfer_created = fields.Boolean(default=False, copy=False)
    source_transfer_id = fields.Many2one("stock.picking", copy=False)

    def button_validate(self):
        # Lưu các phiếu cần tạo Bước 2
        pickings_need_second_transfer = []

        for picking in self:
            # Điều kiện:
            # 1. Là phiếu Internal (INT)
            # 2. Đích là kho transit
            # 3. Chưa từng tạo phiếu Bước 2
            # 4. Có partner_id
            if (picking.picking_type_id.code == 'internal'
                    and not picking.second_transfer_created
                    and not picking.source_transfer_id
                    and picking.partner_id
                    and self._is_inter_warehouse_transit(picking.location_dest_id)):
                
                pickings_need_second_transfer.append(picking)

        # Gọi super để thực hiện validate (của Odoo gốc hoặc các module khác)
        res = super(StockPicking, self).button_validate()

        # Sau khi validate thành công, tạo phiếu Bước 2
        for picking in pickings_need_second_transfer:
            # Refresh picking state
            picking.invalidate_recordset(['state'])
            if picking.state == 'done':
                self.env['hlv.barcode.transit.service'].process_second_transfer(picking)

        return res

    def _is_inter_warehouse_transit(self, location):
        """Kiểm tra location có phải là transit location không."""
        if not location:
            return False
        
        complete_name = (location.complete_name or "").strip().lower()
        accepted_names = [
            "physical locations/inter-warehouse transit",
            "vị trí vật lý/trung chuyển liên kho",
            "kho trung gian"
        ]
        
        name_ok = any(complete_name.endswith(name) or complete_name == name for name in accepted_names)
        return name_ok or location.usage == "transit"
