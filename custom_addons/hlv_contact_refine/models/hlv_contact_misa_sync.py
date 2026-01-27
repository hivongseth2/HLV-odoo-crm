# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging
import requests
import json

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = 'res.partner'

    def action_misa_update_bulk(self):
        """
        Action to update contact information from MISA API for all main contacts (non-delivery).
        Logic:
        1. Search by account_object_code -> Match with Odoo 'company_registry'
        2. If not found, search by account_object_name (exact) -> Match with Odoo 'name'
        Update: company_tax_code -> Odoo 'vat', account_object_code -> Odoo 'company_registry'.
        """
        misa_utils = self.env['misa.api.utils']
        misa_config = self.env['misa.config']
        
        try:
            token = misa_utils._get_misa_token()
            headers = misa_config.get_default_headers(token)
        except Exception as e:
            _logger.error("MISA Auth failed: %s", e)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Lỗi xác thực'),
                    'message': _('Không thể đăng nhập vào MISA: %s') % str(e),
                    'type': 'danger',
                    'sticky': False,
                }
            }

        url = "https://actapp.misa.vn/g1/api/db/v1/list/get_data"
        branch_id = misa_config.get_misa_context().get('BranchId', '53a073a0-5381-4493-820f-51ea32ebe990')
        
        _logger.info("Starting MISA Contact Bulk Update for all main contacts...")

        categories = [
            {"type": "di_customer", "view": "view_account_object_customer", "filter": "[[\"is_customer\",\"=\",true],\"and\",[\"is_employee\",\"=\",false]]"},
            {"type": "di_vendor", "view": "view_account_object_vendor", "filter": "[[\"is_vendor\",\"=\",true],\"and\",[\"is_employee\",\"=\",false]]"}
        ]
        
        misa_records = []
        for cat in categories:
            page_index = 1
            page_size = 200
            
            while True:
                payload = {
                    "sort": json.dumps([{"property": "account_object_code", "desc": False}]),
                    "filter": cat["filter"],
                    "pageIndex": page_index,
                    "pageSize": page_size,
                    "useSp": False,
                    "view": cat["view"],
                    "dataType": cat["type"],
                    "isGetTotal": True,
                    "is_filter_branch": True,
                    "current_branch": branch_id,
                    "is_multi_branch": True,
                    "is_dependent": False,
                    "loadMode": 2
                }

                try:
                    response = misa_utils.sudo()._fetch_with_retry(url, headers, payload)
                    if response.status_code != 200:
                        _logger.error("MISA API failed for %s at page %s: HTTP %s", cat["type"], page_index, response.status_code)
                        break
                    
                    res_json = response.json()
                    if not res_json.get("Success"):
                        _logger.error("MISA API Success=False for %s at page %s: %s", cat["type"], page_index, res_json.get("UserMessage"))
                        break
                    
                    data_obj = res_json.get("Data", [])
                    # Robust parsing for different data structures
                    if isinstance(data_obj, str):
                        try:
                            data_obj = json.loads(data_obj)
                        except Exception:
                            _logger.error("Failed to parse MISA Data string for %s", cat["type"])
                            break
                    
                    if isinstance(data_obj, dict):
                        batch = data_obj.get("PageData", []) or data_obj.get("Data", []) or []
                    elif isinstance(data_obj, list):
                        batch = data_obj
                    else:
                        batch = []

                    if not batch:
                        break
                    
                    misa_records.extend(batch)
                    _logger.info("MISA Fetch %s page %s: %s records", cat["type"], page_index, len(batch))

                    if len(batch) < page_size:
                        break
                    
                    page_index += 1
                    if page_index > 100: break
                        
                except Exception as e:
                    _logger.error("Error calling MISA API for %s at page %s: %s", cat["type"], page_index, str(e))
                    break

        if not misa_records:
             _logger.warning("No records were fetched from MISA API.")
             return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Thông báo'),
                    'message': _('Không tìm thấy dữ liệu từ MISA (Danh sách trống).'),
                    'type': 'warning',
                    'sticky': False,
                }
            }

        _logger.info("Found %s total records from MISA. Updating Odoo partners...", len(misa_records))

        misa_map_by_code = {}
        misa_map_by_name = {}
        
        for r in misa_records:
            if not isinstance(r, dict):
                continue
            code = str(r.get('account_object_code') or '').strip()
            name = str(r.get('account_object_name') or r.get('account_object_name_finance') or '').strip()
            if code:
                misa_map_by_code[code] = r
            if name:
                misa_map_by_name[name] = r

        partners = self.env['res.partner'].sudo().search([('parent_id', '=', False), ('type', '!=', 'delivery')])
        
        updated_count = 0
        for partner in partners:
            misa_data = None
            
            code_val = str(partner.company_registry or '').strip()
            if code_val and code_val in misa_map_by_code:
                misa_data = misa_map_by_code[code_val]
            else:
                name_val = str(partner.name or '').strip()
                if name_val and name_val in misa_map_by_name:
                    misa_data = misa_map_by_name[name_val]
            
            if misa_data:
                vals = {}
                tax_code = str(misa_data.get('company_tax_code') or '').strip()
                if tax_code and partner.vat != tax_code:
                    vals['vat'] = tax_code
                
                obj_code = str(misa_data.get('account_object_code') or '').strip()
                if obj_code and partner.company_registry != obj_code:
                    vals['company_registry'] = obj_code
                
                if vals:
                    partner.sudo().write(vals)
                    updated_count += 1

        _logger.info("MISA Contact Sync completed. Updated %s partners.", updated_count)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Cập nhật hoàn tất'),
                'message': _('Đã quét %s bản ghi MISA và cập nhật thông tin cho %s liên hệ Odoo.') % (len(misa_records), updated_count),
                'type': 'success',
                'sticky': False,
            }
        }
