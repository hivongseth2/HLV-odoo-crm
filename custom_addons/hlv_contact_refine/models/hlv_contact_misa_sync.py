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
        
        # Load all MISA records using pagination
        misa_records = []
        page_index = 1
        page_size = 1000
        
        _logger.info("Starting MISA Contact Sync...")
        
        while True:
            # Based on MISA error message, 'dataType' is required.
            # In AMIS Kế toán, dataType 1 usually refers to AccountObject.
            payload = {
                "dataType": 1,
                "pageIndex": page_index,
                "pageSize": page_size,
                "columns": "account_object_id,account_object_code,account_object_name,company_tax_code,address",
                "loadMode": 2
            }

            try:
                response = misa_utils._fetch_with_retry(url, headers, payload)
                if response.status_code != 200:
                    _logger.error("MISA API failed at page %s: %s", page_index, response.text)
                    break
                
                data = response.json()
                if not data.get("Success"):
                    _logger.error("MISA API Success=False at page %s: %s", page_index, data.get("UserMessage"))
                    break
                
                batch = data.get("Data", [])
                if not batch:
                    break
                
                misa_records.extend(batch)
                
                # Check if we reached the end (if PageCount is provided, or if batch is smaller than page_size)
                # Some MISA APIs return Total or PageCount. If not, we just check batch size.
                if len(batch) < page_size:
                    break
                
                page_index += 1
                if page_index > 50: # Safety break (50,000 records)
                    break
                    
            except Exception as e:
                _logger.exception("Error calling MISA API at page %s", page_index)
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

        _logger.info("Fetched %s records from MISA. Starting update...", len(misa_records))

        # Map MISA data for faster lookup
        misa_map_by_code = {str(r['account_object_code']).strip(): r for r in misa_records if r.get('account_object_code')}
        misa_map_by_name = {str(r['account_object_name']).strip(): r for r in misa_records if r.get('account_object_name')}

        # Get Odoo partners (non-delivery contacts)
        # Only search for main partners (no parent_id)
        partners = self.env['res.partner'].search([('parent_id', '=', False), ('type', '!=', 'delivery')])
        
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
                
                # Update Tax Code
                tax_code = str(misa_data.get('company_tax_code') or '').strip()
                if tax_code and partner.vat != tax_code:
                    vals['vat'] = tax_code
                
                # Update Internal Reference (account_object_code)
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
