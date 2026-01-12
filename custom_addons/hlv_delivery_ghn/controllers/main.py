# -*- coding: utf-8 -*-
import json
import logging
from odoo import http
from odoo.http import request
from ..utils.ghn_api_utils import GHNApiUtils

_logger = logging.getLogger(__name__)

class GHNWebsiteController(http.Controller):

    @http.route('/hlv_ghn/fee/calculate', type='http', auth='public', methods=['POST'], csrf=False)
    def calculate_ghn_fee(self, **kwargs):
        """
        REST API endpoint for WordPress/WooCommerce.
        Expected Header: 'x-api-token'
        Expected JSON Body:
        {
            "province_name": "Hồ Chí Minh",
            "district_name": "Quận Tân Phú",
            "ward_name": "Phường Tân Sơn Nhì",
            "weight": 1000,
            ...
        }
        """
        try:
            body = request.httprequest.data
            params = json.loads(body) if body else {}
            _logger.info("WordPress GHN Request Body: %s", params)
            _logger.info("WordPress GHN Request Headers: %s", dict(request.httprequest.headers))
        except Exception:
            _logger.error("WordPress GHN Request: Invalid JSON body")
            return request.make_response(json.dumps({"success": False, "error": "JSON body không hợp lệ"}), headers=[('Content-Type', 'application/json')])
        
        # 1. Security Check
        company = request.env['res.company'].sudo().search([], limit=1)
        api_token = request.httprequest.headers.get('x-api-token')
        if not company.ghn_wp_api_token or api_token != company.ghn_wp_api_token:
            return request.make_response(json.dumps({"success": False, "error": "Xác thực thất bại (Token API không khớp)"}), headers=[('Content-Type', 'application/json')])

        # 2. Get configuration
        warehouse = company.ghn_default_warehouse_id
        if not warehouse:
            return request.make_response(json.dumps({"success": False, "error": "Chưa cấu hình Kho hàng mặc định cho WooCommerce trong Odoo."}), headers=[('Content-Type', 'application/json')])

        # 3. Map address names to GHN IDs
        Province = request.env['ghn.province'].sudo()
        District = request.env['ghn.district'].sudo()
        Ward = request.env['ghn.ward'].sudo()

        province = Province.search([('name', 'ilike', params.get('province_name'))], limit=1)
        if not province:
            return request.make_response(json.dumps({"success": False, "error": f"Không tìm thấy Tỉnh/Thành: {params.get('province_name')}"}), headers=[('Content-Type', 'application/json')])

        district = District.search([
            ('name', 'ilike', params.get('district_name')),
            ('province_id', '=', province.id)
        ], limit=1)
        if not district:
            return request.make_response(json.dumps({"success": False, "error": f"Không tìm thấy Quận/Huyện: {params.get('district_name')}"}), headers=[('Content-Type', 'application/json')])

        ward = Ward.search([
            ('name', 'ilike', params.get('ward_name')),
            ('district_id', '=', district.id)
        ], limit=1)
        
        if not ward:
            # On-demand sync
            client_temp = GHNApiUtils(company.ghn_api_token, company.ghn_shop_id, company.ghn_environment)
            ghn_wards = client_temp.get_wards(district.district_id)
            for w in ghn_wards:
                if params.get('ward_name', '').lower() in w['WardName'].lower():
                    ward = Ward.create({
                        'ward_code': w['WardCode'],
                        'name': w['WardName'],
                        'district_id': district.id
                    })
                    break
        
        if not ward:
            return request.make_response(json.dumps({"success": False, "error": f"Không tìm thấy Phường/Xã: {params.get('ward_name')}"}), headers=[('Content-Type', 'application/json')])

        # 4. Determine Shop ID and Calculate
        weight = int(params.get('weight', 1000))
        is_heavy = weight > 10000 
        shop_id = company.ghn_shop_id
        if is_heavy:
            shop_id = warehouse.ghn_shop_id_heavy or company.ghn_shop_id_heavy or shop_id
        else:
            shop_id = warehouse.ghn_shop_id or company.ghn_shop_id

        client = GHNApiUtils(company.ghn_api_token, shop_id, company.ghn_environment)
        data = {
            "to_district_id": district.district_id,
            "to_ward_code": ward.ward_code,
            "weight": weight,
            "length": int(params.get('length', 20)),
            "width": int(params.get('width', 20)),
            "height": int(params.get('height', 20)),
            "insurance_value": int(params.get('insurance_value', 0)),
            "cod_value": int(params.get('cod_value', 0)),
            "service_id": int(params.get('service_id', 53320))
        }

        if warehouse.ghn_district_id:
            data["from_district_id"] = warehouse.ghn_district_id.district_id
        if warehouse.ghn_ward_id:
            data["from_ward_code"] = warehouse.ghn_ward_id.ward_code

        result = client.calculate_fee(data)
        _logger.info("WordPress GHN Response: %s", result)
        return request.make_response(json.dumps(result), headers=[('Content-Type', 'application/json')])
