# -*- coding: utf-8 -*-
"""
Extension của purchase.request để:
1. Override requested_by thành Char field để nhận text từ MISA (OwnerIDText)
2. Thêm method api_sync_purchase_request_by_code() cho API endpoint
"""
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime
from dateutil.parser import parse
import logging

_logger = logging.getLogger(__name__)


class PurchaseRequestMisa(models.Model):
    _inherit = 'purchase.request'

    # Override requested_by từ Many2one thành Char để nhận text từ MISA
    requested_by = fields.Char(
        string="Người yêu cầu",
        tracking=True,
        help="Tên người yêu cầu (từ MISA OwnerIDText hoặc nhập thủ công)",
    )

    def _get_purchase_request_payload_by_code(self, purchase_request_no):
        """Tạo payload để tìm Purchase Request theo mã"""
        return {
            "Columns": "SUQsUHVyY2hhc2VSZXF1ZXN0Tm8sUmVxdWVzdERhdGUsT3duZXJJRCxPd25lcklEVGV4dCxQcm9jZXNzU3RhdHVzSUQsUHJvY2Vzc1N0YXR1c0lEVGV4dCxQdXJjaGFzZVN0YXR1c0lELFB1cmNoYXNlU3RhdHVzSURUZXh0LExpc3RQcm9kdWN0SUQsTGlzdFByb2R1Y3RJRFRleHQsRm9ybUxheW91dElELEZvcm1MYXlvdXRJRFRleHQ=",
            "Sorts": [],
            "Start": 0,
            "Page": 1,
            "PageSize": 20,
            "Filters": [
                {
                    "Value": purchase_request_no,
                    "IsDefaultFilter": False,
                    "IsCustomField": False,
                    "IsRelatedField": False,
                    "Operator": 1,  # Equals
                    "Addition": 1,
                    "Property": "PurchaseRequestNo",
                    "InputType": 1,
                    "FieldType": 0,
                    "FieldName": "PurchaseRequestNo",
                    "DisplayField": "Mã yêu cầu mua hàng",
                    "DisplayOperator": "Bằng",
                    "DisplayValue": purchase_request_no
                }
            ],
            "Formula": "",
            "LayoutCode": "PurchaseRequest",
            "DefaultTotal": True,
            "IsMappingData": False,
            "MappingValueObject": {},
            "IsApproved": False,
            "CustomPagingData": {},
            "IsUsedELTS": True,
            "ListGmailPage": [],
            "ListFacebookPage": {},
            "IsListPaging": True,
            "IsGetCache": True,
            "IsCheckInactive": False,
            "IsConverted": False,
            "SessionID": "purchase-request-api",
            "LayoutCodeCheckPermission": "PurchaseRequest",
            "AISearchKeyword": ""
        }

    def _find_or_create_products_from_codes(self, product_codes_text):
        """Tìm sản phẩm từ danh sách mã phân cách bởi dấu phẩy"""
        if not product_codes_text:
            return []
        
        product_lines = []
        codes = [c.strip() for c in product_codes_text.split(',') if c.strip()]
        
        Product = self.env['product.product'].sudo()
        for code in codes:
            product = Product.search([('default_code', '=', code)], limit=1)
            if product:
                product_lines.append({
                    'product_id': product.id,
                    'name': product.name,
                    'product_qty': 1.0,
                    'product_uom_id': product.uom_id.id,
                })
            else:
                _logger.warning("⚠️ Không tìm thấy sản phẩm với mã: %s", code)
        
        return product_lines

    @api.model
    def api_sync_purchase_request_by_code(self, pr_code, create_when_missing=True):
        """
        API method để sync Purchase Request theo mã từ MISA CRM.
        
        Args:
            pr_code: Mã yêu cầu mua hàng (PurchaseRequestNo)
            create_when_missing: Có tạo mới nếu chưa có không
            
        Returns:
            dict: {ok, res_id, name, action, detail}
        """
        if not pr_code:
            return {"ok": False, "error": "missing_pr_code", "message": "Thiếu mã yêu cầu mua hàng"}
        
        _logger.info("🔄 API Sync Purchase Request: %s", pr_code)
        
        try:
            misa_utils = self.env['misa.api.utils']
            misa_config = self.env['misa.config']
            
            # Lấy CRM token
            crm_token = misa_utils._fetch_login_crm_token()
            headers = misa_config.get_crm_header(crm_token)
            
            # Gọi API tìm Purchase Request theo mã
            api_url = "https://amisapp.misa.vn/crm/g1/api/business/PurchaseRequest/Grid"
            payload = self._get_purchase_request_payload_by_code(pr_code)
            
            response = requests.post(api_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            
            requests_data = data.get("Data", [])
            
            if not requests_data:
                return {
                    "ok": False, 
                    "action": "not_found", 
                    "message": f"Không tìm thấy yêu cầu mua hàng {pr_code} trên MISA CRM"
                }
            
            # Lấy dữ liệu đầu tiên
            pr_data = requests_data[0]
            pr_no = pr_data.get("PurchaseRequestNo") or ""
            request_date_str = pr_data.get("RequestDate")
            owner_text = pr_data.get("OwnerIDText") or ""
            product_codes = pr_data.get("ListProductIDText") or ""
            
            # Parse ngày
            request_date = None
            if request_date_str:
                try:
                    request_date = parse(request_date_str).date()
                except Exception:
                    request_date = fields.Date.today()
            
            # Tìm existing
            existing_pr = self.search([('name', '=', pr_no)], limit=1)
            
            if existing_pr:
                # Cập nhật
                vals = {
                    'requested_by': owner_text,
                }
                if request_date:
                    vals['date_start'] = request_date
                
                existing_pr.write(vals)
                _logger.info("✅ Cập nhật Purchase Request: %s", pr_no)
                
                return {
                    "ok": True,
                    "res_id": existing_pr.id,
                    "name": pr_no,
                    "action": "updated",
                    "detail": f"Đã cập nhật yêu cầu mua hàng {pr_no}"
                }
            else:
                if not create_when_missing:
                    return {
                        "ok": False,
                        "action": "not_found",
                        "message": f"Yêu cầu mua hàng {pr_no} chưa tồn tại trong Odoo"
                    }
                
                # Tạo mới
                vals = {
                    'name': pr_no,
                    'date_start': request_date or fields.Date.today(),
                    'requested_by': owner_text,
                    'state': 'to_approve',
                }
                
                new_pr = self.create(vals)
                
                # Tạo các dòng sản phẩm
                product_lines = self._find_or_create_products_from_codes(product_codes)
                PurchaseRequestLine = self.env['purchase.request.line'].sudo()
                for pline in product_lines:
                    PurchaseRequestLine.create({
                        'request_id': new_pr.id,
                        'product_id': pline['product_id'],
                        'name': pline['name'],
                        'product_qty': pline['product_qty'],
                        'product_uom_id': pline['product_uom_id'],
                    })
                
                _logger.info("✅ Tạo mới Purchase Request: %s (%d sản phẩm)", pr_no, len(product_lines))
                
                return {
                    "ok": True,
                    "res_id": new_pr.id,
                    "name": pr_no,
                    "action": "created",
                    "detail": f"Đã tạo yêu cầu mua hàng {pr_no} với {len(product_lines)} sản phẩm"
                }
                
        except requests.exceptions.RequestException as e:
            _logger.exception("❌ Lỗi kết nối MISA API: %s", e)
            return {"ok": False, "error": "api_error", "message": str(e)}
        except Exception as e:
            _logger.exception("❌ Lỗi sync Purchase Request: %s", e)
            return {"ok": False, "error": "exception", "message": str(e)}
