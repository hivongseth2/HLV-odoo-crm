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
        p_input = str(params.get('province_name', ''))
        province = False
        if p_input.isdigit():
            province = Province.search([('province_id', '=', int(p_input))], limit=1)
        
        if not province:
            p_norm = self._normalize(p_input)
            province = Province.search([]).filtered(lambda x: self._normalize(x.name) == p_norm)
        
        if not province:
            province = Province.search([('name', 'ilike', p_input)], limit=1)
        
        if not province:
            _logger.error("GHN API: Province not found for '%s'", p_input)
            return request.make_response(json.dumps({"success": False, "error": f"Không tìm thấy Tỉnh: {p_input}"}), headers=[('Content-Type', 'application/json')])

        # District Search
        d_input = str(params.get('district_name', ''))
        district = False
        if d_input.isdigit():
            district = District.search([('district_id', '=', int(d_input)), ('province_id', '=', province.id)], limit=1)
        
        if not district and d_input:
            d_norm = self._normalize(d_input)
            district = District.search([('province_id', '=', province.id)]).filtered(lambda x: self._normalize(x.name) == d_norm)
            if not district:
                district = District.search([('name', 'ilike', d_input), ('province_id', '=', province.id)], limit=1)
        
        ward = False
        w_input = str(params.get('ward_name', ''))

        # Fallback: If district is missing but we have a Ward Code (numeric)
        if not district and w_input.isdigit():
            _logger.info("WordPress GHN: District missing, reverse searching Ward ID: %s", w_input)
            target_ward = Ward.search([('ward_code', '=', w_input), ('district_id.province_id', '=', province.id)], limit=1)
            if target_ward:
                ward = target_ward
                district = ward.district_id
                _logger.info("WordPress GHN: Reverse search found District: %s", district.name)

        # If still no district, return 0 fee
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
        if not warehouse or not warehouse.ghn_district_id:
            return request.make_response(json.dumps({"success": False, "error": "Kho hàng mặc định chưa được cấu hình địa chỉ (Quận/Huyện) trên Odoo."}), headers=[('Content-Type', 'application/json')])

        # Calculate weight and dimensions from Odoo products if items are provided
        weight = 0
        p_length = 0
        p_width = 0
        p_height = 0
        
        items = params.get('items', [])
        if items:
            for item in items:
                sku = item.get('sku')
                qty = int(item.get('qty', 1))
                if sku:
                    product = request.env['product.product'].sudo().search([('default_code', '=', sku)], limit=1)
                    if product:
                        # Odoo weight is in kg, convert to grams
                        weight += (product.weight or 1) * qty
                        # Aggregate dimensions (Simple logic: Sum height, max length/width)
                        p_length = max(p_length, product.product_length or 0)
                        p_width = max(p_width, product.product_width or 0)
                        p_height += (product.product_height or 0) * qty
            
            if weight > 0:
                weight = int(weight * 1000)

        # Fallback to WordPress values if Odoo lookup failed or no items
        if weight == 0:
            weight = int(params.get('weight', 1000))
        if p_length == 0:
            p_length = int(params.get('length', 20))
        if p_width == 0:
            p_width = int(params.get('width', 20))
        if p_height == 0:
            p_height = int(params.get('height', 20))

        # GHN minimum requirement is usually 1cm, ensrue no 0 values
        p_length = max(p_length, 1)
        p_width = max(p_width, 1)
        p_height = max(p_height, 1)

        shop_id = (warehouse.ghn_shop_id_heavy if weight > 10000 else warehouse.ghn_shop_id) or company.ghn_shop_id
        
        client = GHNApiUtils(company.ghn_api_token, shop_id, company.ghn_environment)
        from_district_id = warehouse.ghn_district_id.district_id
        to_district_id = district.district_id

        # Determine Service IDs
        service_id = params.get('service_id')
        available_services_list = []
        if not service_id:
            res_services = client.get_services(from_district_id, to_district_id)
            if res_services.get('success'):
                available_services_list = res_services.get('data') or []
        else:
            available_services_list = [{'service_id': int(service_id), 'short_name': 'Dịch vụ đã chọn'}]
        
        calculated_results = []
        for svc in available_services_list:
            svc_id = svc.get('service_id')
            if not svc_id: continue
            
            data = {
                "from_district_id": from_district_id, "to_district_id": to_district_id,
                "to_ward_code": ward.ward_code, "weight": weight,
                "length": int(p_length), "width": int(p_width),
                "height": int(p_height), "service_id": int(svc_id)
            }
            if warehouse.ghn_ward_id: data["from_ward_code"] = warehouse.ghn_ward_id.ward_code

            res_fee = client.calculate_fee(data)
            if res_fee.get('success'):
                calculated_results.append({
                    'service_id': svc_id,
                    'name': svc.get('short_name') or svc.get('name') or "Giao hàng nhanh",
                    'total': res_fee['data'].get('total', 0)
                })

        if not calculated_results:
            return request.make_response(json.dumps({"success": False, "error": "Không tìm thấy dịch vụ vận chuyển nào phù hợp."}), headers=[('Content-Type', 'application/json')])

        _logger.info("WordPress GHN Results: %s services found", len(calculated_results))
        return request.make_response(json.dumps({
            "success": True, 
            "services": calculated_results,
            "data": calculated_results[0] # Backward compatibility
        }), headers=[('Content-Type', 'application/json')])
