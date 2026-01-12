# -*- coding: utf-8 -*-
from odoo import fields, models, api
from ..utils.ghn_api_utils import GHNApiUtils
import logging

_logger = logging.getLogger(__name__)

class GHNFeeWizard(models.TransientModel):
    _name = "ghn.fee.wizard"
    _description = "GHN Calculate Fee Wizard"

    picking_id = fields.Many2one("stock.picking", string="Picking")
    
    # Destination Address
    province_id = fields.Many2one("ghn.province", string="Province", required=True)
    district_id = fields.Many2one("ghn.district", string="District", required=True, 
                                domain="[('province_id', '=', province_id)]")
    ward_id = fields.Many2one("ghn.ward", string="Ward", required=True,
                             domain="[('district_id', '=', district_id)]")
    
    # Package Info (Defaults from picking if available)
    weight = fields.Integer(string="Weight (gram)", default=1000)
    length = fields.Integer(string="Length (cm)", default=20)
    width = fields.Integer(string="Width (cm)", default=20)
    height = fields.Integer(string="Height (cm)", default=20)
    
    # Other Info
    insurance_value = fields.Integer(string="Insurance Value", default=0)
    cod_value = fields.Integer(string="COD Value", default=0)
    
    # Service
    service_id = fields.Selection(selection="_get_services", string="Service", required=True)
    
    # Result
    fee_result = fields.Float(string="Shipping Fee", readonly=True)
    message = fields.Text(string="Message", readonly=True)

    def _get_api_client(self):
        company = self.env.company
        return GHNApiUtils(
            token=company.ghn_api_token,
            shop_id=company.ghn_shop_id,
            environment=company.ghn_environment
        )

    @api.onchange('district_id')
    def _onchange_district(self):
        """Fetch wards from GHN when district changes and cache them if not already."""
        if not self.district_id:
            return
        
        client = self._get_api_client()
        wards = client.get_wards(self.district_id.district_id)
        
        WardModel = self.env['ghn.ward']
        for w in wards:
            exist = WardModel.search([
                ('ward_code', '=', w['WardCode']),
                ('district_id', '=', self.district_id.id)
            ], limit=1)
            if not exist:
                WardModel.create({
                    'ward_code': w['WardCode'],
                    'name': w['WardName'],
                    'district_id': self.district_id.id
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
        
        result = client.calculate_fee(data)
        if result.get('success'):
            self.fee_result = result['data'].get('total', 0)
            self.message = "Shipping fee calculated successfully."
        else:
            self.message = f"GHN API Error: {result.get('error')}"
            
        return {
            "type": "ir.actions.act_window",
            "res_model": "ghn.fee.wizard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }
