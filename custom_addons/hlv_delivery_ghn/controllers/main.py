# -*- coding: utf-8 -*-
import json
import logging
from odoo import http
from odoo.http import request
from ..utils.ghn_api_utils import GHNApiUtils

_logger = logging.getLogger(__name__)

class GHNWebsiteController(http.Controller):

    def _normalize(self, text):
        """Helper to remove accents and spaces for better matching."""
        if not text:
            return ""
        import unicodedata
        import re
        text = str(text)
        # Convert to NFC, lowercase, remove spaces
        text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
        text = text.lower().replace(" ", "")
        return text

    @http.route('/hlv_ghn/fee/calculate', type='http', auth='public', methods=['POST'], csrf=False)
    def calculate_ghn_fee(self, **kwargs):
        try:
            body = request.httprequest.data
            params = json.loads(body) if body else {}
            _logger.info("WordPress GHN Request Body: %s", params)
        except Exception:
            return request.make_response(json.dumps({"success": False, "error": "JSON body không hợp lệ"}), headers=[('Content-Type', 'application/json')])
        
        # 1. Security Check
        company = request.env['res.company'].sudo().search([], limit=1)
        api_token = request.httprequest.headers.get('x-api-token')
        if not company.ghn_wp_api_token or api_token != company.ghn_wp_api_token:
            _logger.warning("WordPress GHN Auth Failed. Token: %s", api_token)
            return request.make_response(json.dumps({"success": False, "error": "Xác thực thất bại"}), headers=[('Content-Type', 'application/json')])

        # 2. Map address
        Province = request.env['ghn.province'].sudo()
        District = request.env['ghn.district'].sudo()
        Ward = request.env['ghn.ward'].sudo()

        # Province Search
        p_name = params.get('province_name', '')
        p_norm = self._normalize(p_name)
        province = Province.search([]).filtered(lambda x: self._normalize(x.name) == p_norm)
        if not province:
            province = Province.search([('name', 'ilike', p_name)], limit=1)
        
        if not province:
            _logger.error("GHN API: Province not found for '%s'", p_name)
            return request.make_response(json.dumps({"success": False, "error": f"Không tìm thấy Tỉnh: {p_name}"}), headers=[('Content-Type', 'application/json')])

        # District Search
        d_name = params.get('district_name', '')
        d_norm = self._normalize(d_name)
        district = False
        
        if d_norm:
            district = District.search([('province_id', '=', province.id)]).filtered(lambda x: self._normalize(x.name) == d_norm)
            if not district and d_name:
                district = District.search([('name', 'ilike', d_name), ('province_id', '=', province.id)], limit=1)
        
        ward = False
        w_input = str(params.get('ward_name', ''))

        # Fallback: If district is missing but we have a Ward Code (numeric)
        if not district and w_input.isdigit():
            ward = Ward.search([('ward_code', '=', w_input), ('district_id.province_id', '=', province.id)], limit=1)
            if ward:
                district = ward.district_id

        # If still no district, return 0 fee (Don't error out to avoid WP caching failure)
        if not district:
            _logger.info("WordPress GHN: District not provided yet. Returning 0.")
            return request.make_response(json.dumps({"success": True, "message": "Vui lòng chọn Quận/Huyện", "total": 0, "fee": 0}), headers=[('Content-Type', 'application/json')])

        # Normal Ward Search
        if not ward:
            if w_input.isdigit():
                ward = Ward.search([('ward_code', '=', w_input), ('district_id', '=', district.id)], limit=1)
            
            if not ward:
                w_norm = self._normalize(w_input)
                ward = Ward.search([('district_id', '=', district.id)]).filtered(lambda x: self._normalize(x.name) == w_norm)
            
            if not ward and w_input:
                # On-demand sync
                client_temp = GHNApiUtils(company.ghn_api_token, company.ghn_shop_id, company.ghn_environment)
                ghn_wards = client_temp.get_wards(district.district_id)
                for w in ghn_wards:
                    if self._normalize(w['WardName']) == self._normalize(w_input) or w['WardCode'] == w_input:
                        ward = Ward.create({'ward_code': w['WardCode'], 'name': w['WardName'], 'district_id': district.id})
                        break

        # If no ward, return 0 fee
        if not ward:
            _logger.info("WordPress GHN: Ward not provided yet. Returning 0.")
            return request.make_response(json.dumps({"success": True, "message": "Vui lòng chọn Phường/Xã", "total": 0, "fee": 0}), headers=[('Content-Type', 'application/json')])

        # 3. Calculate
        warehouse = company.ghn_default_warehouse_id
        weight = int(params.get('weight', 1000))
        shop_id = (warehouse.ghn_shop_id_heavy if weight > 10000 else warehouse.ghn_shop_id) or company.ghn_shop_id
        
        client = GHNApiUtils(company.ghn_api_token, shop_id, company.ghn_environment)
        data = {
            "to_district_id": district.district_id, "to_ward_code": ward.ward_code,
            "weight": weight, "length": int(params.get('length', 20)),
            "width": int(params.get('width', 20)), "height": int(params.get('height', 20)),
            "service_id": int(params.get('service_id', 53320))
        }
        if warehouse.ghn_district_id: data["from_district_id"] = warehouse.ghn_district_id.district_id
        if warehouse.ghn_ward_id: data["from_ward_code"] = warehouse.ghn_ward_id.ward_code

        result = client.calculate_fee(data)
        _logger.info("WordPress GHN Response: %s", result)
        return request.make_response(json.dumps(result), headers=[('Content-Type', 'application/json')])
