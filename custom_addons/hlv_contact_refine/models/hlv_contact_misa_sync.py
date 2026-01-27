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
        1. Search by account_object_code -> Match with Odoo 'ref'
        2. If not found, search by account_object_name (exact) -> Match with Odoo 'name'
        Update: company_tax_code -> Odoo 'vat', account_object_code -> Odoo 'ref' (if matched by name).
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
        
        # We perform two passes: one for customers and one for vendors to ensure all contacts are updated
        categories = [
            {"type": "di_customer", "view": "view_account_object_customer", "filter": "[[\"is_customer\",\"=\",true],\"and\",[\"is_employee\",\"=\",false]]"},
            {"type": "di_vendor", "view": "view_account_object_vendor", "filter": "[[\"is_vendor\",\"=\",true],\"and\",[\"is_employee\",\"=\",false]]"}
        ]
        
        misa_records = []
        _logger.info("Starting MISA Contact Sync with custom payload...")
        
        for cat in categories:
            page_index = 1
            page_size = 500 # Smaller batch size to avoid timeout with rich views
            
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
                        _logger.error("MISA API failed for %s at page %s: %s", cat["type"], page_index, response.text)
                        break
                    
                    data = response.json()
                    if not data.get("Success"):
                        _logger.error("MISA API Success=False for %s at page %s: %s", cat["type"], page_index, data.get("UserMessage"))
                        break
                    
                    batch = data.get("Data", [])
                    if not batch:
                        break
                    
                    misa_records.extend(batch)
                    if len(batch) < page_size:
                        break
                    
                    page_index += 1
                    if page_index > 100: break # Safety break
                        
                except Exception as e:
                    _logger.exception("Error calling MISA API for %s at page %s", cat["type"], page_index)
                    break

        if not misa_records:
             return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Thông báo'),
                    'message': _('Không tìm thấy dữ liệu từ MISA hoặc có lỗi trong quá trình lấy dữ liệu.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }

        _logger.info("Fetched %s total records from MISA (Customers + Vendors). Starting update...", len(misa_records))

        # Use dictionaries for fast lookup
        misa_map_by_code = {}
        misa_map_by_name = {}
        
        for r in misa_records:
            code = str(r.get('account_object_code') or '').strip()
            name = str(r.get('account_object_name') or r.get('account_object_name_finance') or '').strip()
            if code:
                misa_map_by_code[code] = r
            if name:
                misa_map_by_name[name] = r

        # Get Odoo partners (non-delivery contacts)
        partners = self.env['res.partner'].sudo().search([('parent_id', '=', False), ('type', '!=', 'delivery')])
        
        updated_count = 0
        for partner in partners:
            misa_data = None
            
            # 1. Match by Code (ref)
            ref_val = str(partner.ref or '').strip()
            if ref_val and ref_val in misa_map_by_code:
                misa_data = misa_map_by_code[ref_val]
            
            # 2. Match by Name (exact)
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
                if obj_code and partner.ref != obj_code:
                    vals['ref'] = obj_code
                
                if vals:
                    partner.write(vals)
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
