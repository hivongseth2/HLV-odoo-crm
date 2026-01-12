# -*- coding: utf-8 -*-
from odoo import fields, models, api
from ..utils.ghn_api_utils import GHNApiUtils
import logging

_logger = logging.getLogger(__name__)

class GHNFeeWizard(models.TransientModel):
    _name = "ghn.fee.wizard"
    _description = "GHN Calculate Fee Wizard"

    picking_id = fields.Many2one("stock.picking", string="Picking")
    
    # Địa chỉ gửi (Tùy chọn - GHN sẽ dùng địa chỉ mặc định của shop nếu để trống)
    from_province_id = fields.Many2one("ghn.province", string="Tỉnh/Thành gửi")
    from_district_id = fields.Many2one("ghn.district", string="Quận/Huyện gửi",
                                     domain="[('province_id', '=', from_province_id)]")
    from_ward_id = fields.Many2one("ghn.ward", string="Phường/Xã gửi",
                                  domain="[('district_id', '=', from_district_id)]")

    # Địa chỉ nhận
    province_id = fields.Many2one("ghn.province", string="Tỉnh/Thành nhận", required=True)
    district_id = fields.Many2one("ghn.district", string="Quận/Huyện nhận", required=True, 
                                domain="[('province_id', '=', province_id)]")
    ward_id = fields.Many2one("ghn.ward", string="Phường/Xã nhận", required=True,
                             domain="[('district_id', '=', district_id)]")
    
    # Thông tin kiện hàng
    weight = fields.Integer(string="Khối lượng (gram)", default=1000)
    length = fields.Integer(string="Chiều dài (cm)", default=20)
    width = fields.Integer(string="Chiều rộng (cm)", default=20)
    height = fields.Integer(string="Chiều cao (cm)", default=20)
    
    # Thông tin khác
    insurance_value = fields.Integer(string="Giá trị bảo hiểm", default=0)
    cod_value = fields.Integer(string="Tiền thu hộ (COD)", default=0)
    
    # Dịch vụ
    service_id = fields.Selection(selection="_get_services", string="Dịch vụ", required=True)
    
    # Kết quả
    fee_result = fields.Float(string="Cước phí vận chuyển", readonly=True)
    message = fields.Text(string="Thông báo", readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super(GHNFeeWizard, self).default_get(fields_list)
        picking_id = res.get('picking_id') or self._context.get('default_picking_id')
        if picking_id:
            picking = self.env['stock.picking'].browse(picking_id)
            warehouse = picking.picking_type_id.warehouse_id
            if warehouse:
                if warehouse.ghn_province_id:
                    res['from_province_id'] = warehouse.ghn_province_id.id
                if warehouse.ghn_district_id:
                    res['from_district_id'] = warehouse.ghn_district_id.id
                if warehouse.ghn_ward_id:
                    res['from_ward_id'] = warehouse.ghn_ward_id.id
                    
            # Auto-populate receiver address from picking partner if available
            partner = picking.partner_id
            if partner:
                # This part is optional but helpful if you want to automate receiver too
                pass
        return res

    def _get_api_client(self):
        company = self.env.company
        shop_id = company.ghn_shop_id
        
        # Determine the correct Shop ID based on weight and warehouse config
        picking = self.picking_id
        warehouse = picking.picking_type_id.warehouse_id
        
        is_heavy = self.weight > 10000 # 10kg
        
        if is_heavy:
            # Try warehouse heavy shop id, then company heavy shop id
            shop_id = (warehouse and warehouse.ghn_shop_id_heavy) or company.ghn_shop_id_heavy or shop_id
        else:
            # Try warehouse standard shop id, then company standard shop id
            shop_id = (warehouse and warehouse.ghn_shop_id) or company.ghn_shop_id
            
        return GHNApiUtils(
            token=company.ghn_api_token,
            shop_id=shop_id,
            environment=company.ghn_environment
        )

    @api.onchange('from_district_id', 'district_id')
    def _onchange_district_any(self):
        """Fetch wards from GHN when district changes (both sender and receiver)."""
        district = self.from_district_id or self.district_id
        if not district:
            return
        
        client = self._get_api_client()
        wards = client.get_wards(district.district_id)
        
        WardModel = self.env['ghn.ward']
        for w in wards:
            exist = WardModel.search([
                ('ward_code', '=', w['WardCode']),
                ('district_id', '=', district.id)
            ], limit=1)
            if not exist:
                WardModel.create({
                    'ward_code': w['WardCode'],
                    'name': w['WardName'],
                    'district_id': district.id
                })

    def _get_services(self):
        # We need a district_id to get services.
        # This is a bit tricky for static selection. 
        # I'll use a hardcoded common services list or fetch dynamically in action.
        return [
            ('53320', 'Chuyển phát chuẩn'),
            ('53321', 'Chuyển phát nhanh'),
            ('53322', 'Chuyển phát tiết kiệm')
        ]

    def action_calculate_fee(self):
        client = self._get_api_client()
        
        # Determine service_id if not explicitly set (or use selected)
        service_id = int(self.service_id)
        
        data = {
            "to_district_id": self.district_id.district_id,
            "to_ward_code": self.ward_id.ward_code,
            "weight": self.weight,
            "length": self.length,
            "width": self.width,
            "height": self.height,
            "insurance_value": self.insurance_value,
            "cod_value": self.cod_value,
            "service_id": service_id
        }

        if self.from_district_id:
            data["from_district_id"] = self.from_district_id.district_id
        if self.from_ward_id:
            data["from_ward_code"] = self.from_ward_id.ward_code
        
        result = client.calculate_fee(data)
        if result.get('success'):
            self.fee_result = result['data'].get('total', 0)
            self.message = "Tính phí vận chuyển thành công."
        else:
            self.message = f"Lỗi API GHN: {result.get('error')}"
            
        return {
            "type": "ir.actions.act_window",
            "res_model": "ghn.fee.wizard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }
