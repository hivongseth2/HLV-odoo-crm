# -*- coding: utf-8 -*-
"""
Extension của purchase.request để:
1. Thêm field misa_requester_text để nhận text từ MISA (OwnerIDText)
2. Override requested_by để không bắt buộc (dữ liệu từ MISA dùng misa_requester_text)
3. Thêm method api_sync_purchase_request_by_code() cho API endpoint
4. Tự động tạo sản phẩm nếu chưa có (lấy tên từ MISA)
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

    # Thêm field mới để lưu tên người yêu cầu từ MISA
    misa_requester_text = fields.Char(
        string="Người yêu cầu (MISA)",
        tracking=True,
        help="Tên người yêu cầu được đồng bộ từ MISA CRM (OwnerIDText)",
    )

    # Override requested_by để bỏ required=True
    requested_by = fields.Many2one(
        comodel_name="res.users",
        string="Người yêu cầu",
        required=False,
        copy=False,
        tracking=True,
        index=True,
    )

    def _find_user_by_name(self, name):
        """Tìm user Odoo theo tên hoặc login"""
        if not name:
            return False
        name = name.strip()
        User = self.env['res.users'].sudo()
        user = User.search(['|', ('name', '=', name), ('login', '=', name)], limit=1)
        if not user:
            user = User.search(['|', ('name', 'ilike', name), ('login', 'ilike', name)], limit=1)
        return user.id if user else False

    def _get_purchase_request_payload_by_code(self, purchase_request_no):
        """Tạo payload để tìm Purchase Request theo mã"""
        import uuid
        # Base64 decoded: ID,PurchaseRequestNo,RequestDate,OwnerID,OwnerIDText,ProcessStatusID,ProcessStatusIDText,PurchaseStatusID,PurchaseStatusIDText,ListProductID,ListProductIDText,FormLayoutID,FormLayoutIDText,ProcessID,URLViewProcess,SaleOrderIDText
        columns_b64 = "SUQsUHVyY2hhc2VSZXF1ZXN0Tm8sUmVxdWVzdERhdGUsT3duZXJJRCxPd25lcklEVGV4dCxQcm9jZXNzU3RhdHVzSUQsUHJvY2Vzc1N0YXR1c0lEVGV4dCxQdXJjaGFzZVN0YXR1c0lELFB1cmNoYXNlU3RhdHVzSURUZXh0LExpc3RQcm9kdWN0SUQsTGlzdFByb2R1Y3RJRFRleHQsRm9ybUxheW91dElELEZvcm1MYXlvdXRJRFRleHQsUHJvY2Vzc0lELFVSTFZpZXdQcm9jZXNzLFNhbGVPcmRlcklEVGV4dA=="
        return {
            "Columns": columns_b64,
            "Sorts": [
                {
                    "SortBy": "ModifiedDate",
                    "Type": 0,
                    "SortDirection": 1
                }
            ],
            "Start": 0,
            "Page": 1,
            "PageSize": 20,
            "Filters": [
                {
                    "Value": purchase_request_no.strip(),
                    "IsDefaultFilter": False,
                    "IsCustomField": False,
                    "IsRelatedField": False,
                    "ModuleRelated": "",
                    "FromFilterCustom": False,
                    "ValueDisplayText": "",
                    "isValueDateNumber": False,
                    "IsSearchModule": False,
                    "ConfigDisplayRelatedField": "",
                    "ConfigSubDisplayRelatedField": "",
                    "ConfigSearchField": [],
                    "ConfigUrlCbx": "",
                    "FilterObjects": [],
                    "dataOperator": [],
                    "IsProductCategory": False,
                    "SelectedDataList": [],
                    "IsCustomTypeDecimalDigits": False,
                    "IsFromFormula": False,
                    "Operator": 1,
                    "Addition": 1,
                    "Property": "PurchaseRequestNo",
                    "InputType": 1,
                    "FieldType": 0,
                    "FieldName": "PurchaseRequestNo",
                    "OperatorBeforeDetectChanges": 1,
                    "InputTypeOrigin": 1,
                    "DisplayField": "Mã yêu cầu mua hàng",
                    "DisplayOperator": "Chứa",
                    "DisplayValue": purchase_request_no.strip(),
                    "ValueOrigin": purchase_request_no.strip()
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
            "SessionID": str(uuid.uuid4()),
            "LayoutCodeCheckPermission": "PurchaseRequest",
            "AISearchKeyword": ""
        }





    def _get_default_approver(self):
        """Lấy người phê duyệt mặc định (Manager của PR)"""
        manager_group = self.env.ref("purchase_request.group_purchase_request_manager", raise_if_not_found=False)
        if manager_group and manager_group.users:
            return manager_group.users[0].id
        return False

    def _find_or_create_products_from_codes(self, product_codes_text, token=None):
        """Tìm hoặc tạo sản phẩm từ danh sách mã phân cách bởi dấu phẩy"""
        if not product_codes_text:
            return []
        
        product_lines = []
        codes = [c.strip() for c in product_codes_text.split(',') if c.strip()]
        
        Product = self.env['product.product'].sudo()
        OdooUtils = self.env['odoo.utils'].sudo()
        MisaUtils = self.env['misa.api.utils'].sudo()
        
        # Lấy token một lần nếu chưa có để dùng cho cả loop
        if not token and any(not Product.search([('default_code', '=', c)], limit=1) for c in codes):
            token = MisaUtils._fetch_login_crm_token()

        for code in codes:
            # 1. Tìm trong Odoo trước
            product = Product.search([('default_code', '=', code)], limit=1)
            
            if not product:
                # 2. Nếu không có, tìm thông tin từ MISA CRM
                _logger.info("🔍 Đang tìm thông tin sản phẩm %s từ MISA...", code)
                try:
                    misa_products = MisaUtils.search_product_by_name(code=code, limit=1, token=token)
                    if misa_products:
                        m_prod = misa_products[0]
                        m_name = m_prod.get('name') or code
                        m_unit = m_prod.get('unit') or 'Cái'
                        m_price = m_prod.get('price') or 0.0
                        
                        # Tạo mới bằng odoo.utils (để đồng nhất với PO/SO sync)
                        product = OdooUtils._get_or_create_product(
                            code=code,
                            name=m_name,
                            unit_name=m_unit,
                            cost=m_price,
                            purchase_ok=True,
                            sale_ok=True
                        )
                        _logger.info("🆕 Đã tạo sản phẩm mới từ MISA: %s (%s)", code, m_name)
                    else:
                        # Fallback nếu MISA cũng không thấy
                        product = OdooUtils._get_or_create_product(
                            code=code,
                            name=code,
                            unit_name='Cái',
                            purchase_ok=True,
                            sale_ok=True
                        )
                        _logger.warning("⚠️ Không tìm thấy sản phẩm %s trên MISA, tạo tạm với tên=code", code)
                except Exception as e:
                    _logger.error("❌ Lỗi khi fetch sản phẩm %s từ MISA: %s", code, e)
                    # Fallback cuối cùng
                    product = OdooUtils._get_or_create_product(code=code, name=code, unit_name='Cái')

            if product:
                product_lines.append({
                    'product_id': product.id,
                    'name': product.name,
                    'product_qty': 1.0,
                    'product_uom_id': product.uom_id.id,
                })
        
        return product_lines

    @api.model
    def api_sync_purchase_request_by_code(self, pr_code, create_when_missing=True):
        if not pr_code:
            return {"ok": False, "error": "missing_pr_code", "message": "Thiếu mã yêu cầu mua hàng"}
        
        try:
            misa_utils = self.env['misa.api.utils']
            misa_config = self.env['misa.config']
            crm_token = misa_utils._fetch_login_crm_token()
            headers = misa_config.get_crm_header(crm_token)
            
            api_url = "https://amisapp.misa.vn/crm/g1/api/business/PurchaseRequest/Grid"
            payload = self._get_purchase_request_payload_by_code(pr_code)
            
            _logger.info("📡 Requesting MISA PR API: %s | Payload: %s", api_url, payload)
            
            response = requests.post(api_url, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            
            _logger.info("📡 MISA PR API Response: %s", data)
            
            requests_data = data.get("Data", [])
            _logger.info("🔍 MISA PR Found: %s records", len(requests_data))
            
            if not requests_data:

                return {"ok": False, "action": "not_found", "message": f"Không tìm thấy yêu cầu {pr_code}"}
            
            pr_data = requests_data[0]
            pr_no = pr_data.get("PurchaseRequestNo") or ""
            request_date_str = pr_data.get("RequestDate")
            owner_text = pr_data.get("OwnerIDText") or ""
            product_codes = pr_data.get("ListProductIDText") or ""
            sale_order_text = pr_data.get("SaleOrderIDText") or ""
            
            request_date = None
            if request_date_str:
                try:
                    request_date = parse(request_date_str).date()
                except Exception:
                    request_date = fields.Date.today()
            
            odoo_user_id = self._find_user_by_name(owner_text)
            
            existing_pr = self.search([('name', '=', pr_no)], limit=1)
            if existing_pr:
                vals = {
                    'misa_requester_text': owner_text,
                    'requested_by': odoo_user_id,
                    'origin': sale_order_text,
                }
                if request_date:
                    vals['date_start'] = request_date
                existing_pr.write(vals)

                return {"ok": True, "res_id": existing_pr.id, "name": pr_no, "action": "updated"}
            else:
                if not create_when_missing:
                    return {"ok": False, "message": "Yêu cầu chưa tồn tại"}
                
                vals = {
                    'name': pr_no,
                    'date_start': request_date or fields.Date.today(),
                    'misa_requester_text': owner_text,
                    'requested_by': odoo_user_id,
                    'assigned_to': self._get_default_approver(),
                    'state': 'to_approve',
                    'origin': sale_order_text,
                }

                new_pr = self.create(vals)
                
                product_lines = self._find_or_create_products_from_codes(product_codes, token=crm_token)
                PurchaseRequestLine = self.env['purchase.request.line'].sudo()
                for pline in product_lines:
                    PurchaseRequestLine.create({
                        'request_id': new_pr.id,
                        'product_id': pline['product_id'],
                        'name': pline['name'],
                        'product_qty': pline['product_qty'],
                        'product_uom_id': pline['product_uom_id'],
                    })
                return {"ok": True, "res_id": new_pr.id, "name": pr_no, "action": "created"}

                
        except Exception as e:
            _logger.exception("❌ Lỗi sync Purchase Request: %s", e)
            return {"ok": False, "error": "exception", "message": str(e)}
