# -*- coding: utf-8 -*-
"""
Self-contained MISA CRM API facade.

All API logic lives here — NO dependency on misa_fetch_po_button.
If MISA endpoints or auth flow change, only THIS file needs updating.
"""
import json
import logging
import re
import uuid
from datetime import datetime, timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from odoo import models

_logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================
_MISA_CONTEXT = {
    "TenantId": "47ab503b-99d5-4eb8-aa11-24927abb3585",
    "TenantCode": "3R2PY2F4",
    "DatabaseId": "f4b18d63-6c99-4a53-b974-f6208e84fced",
    "BranchId": "53a073a0-5381-4493-820f-51ea32ebe990",
    "WorkingBook": 0,
    "Language": "vi",
    "IncludeDependentBranch": "False",
    "SessionId": (
        "ss1547cc69a995421e91347736dabe6cb9"
        ".693017cdc24074e96e4756afbf2b6ab6"
        ".f4b18d636c994a53b974f6208e84fced"
        ".638877626393411146"
    ),
    "DBType": 1,
    "AuthType": 0,
    "AmisSessionId": (
        "NAA3AGEAYgA1ADAAMwBiADkAOQBkADUANABlAGIAOABhAGEAMQAxADIA"
        "NAA5ADIANwBhAGIAYgAzADUAOAA1ADkAMgBiADgANABhADYAZgBiADYA"
        "ZQBiADQANwBhADgAYQA0AGUAMgBhAGUAYgAzAGEAZQA2ADMAYgA0ADYA"
        "YwA="
    ),
    "HasAgent": False,
    "UserType": 1,
    "art": 1,
    "UserId": "1547cc69-a995-421e-9134-7736dabe6cb9",
    "isc": False,
}

_LOGIN_EMAIL = "thanhluan.hlv@gmail.com"
_LOGIN_PASSWORD = "ThanhLuan1303@"
_COMPANY_CODE = "3R2PY2F4"
_DB_ID = "f4b18d63-6c99-4a53-b974-f6208e84fced"
_TENANT_ID = "47ab503b-99d5-4eb8-aa11-24927abb3585"
_USER_ID = "1547cc69-a995-421e-9134-7736dabe6cb9"
_X_DEVICE = "693017cdc24074e96e4756afbf2b6ab6"
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0"
)


class MisaCrmApi(models.AbstractModel):
    _name = 'misa.crm.api'
    _description = 'MISA CRM API Facade (self-contained)'

    # =====================================================================
    # HTTP helpers
    # =====================================================================
    @staticmethod
    def _retry_session():
        s = requests.Session()
        retry = Retry(total=3, backoff_factor=1,
                      status_forcelist=[500, 502, 503, 504])
        s.mount("https://", HTTPAdapter(max_retries=retry))
        return s

    # =====================================================================
    # Auth — actapp token  (for purchase voucher API)
    # =====================================================================
    def _get_actapp_token(self):
        login_url = "https://amisapp.misa.vn/APIS/AuthenAPI/api/Account/login"
        login_payload = {
            "UserName": _LOGIN_EMAIL,
            "Password": _LOGIN_PASSWORD,
        }
        login_headers = {
            "Content-Type": "application/json",
            "User-Agent": _BROWSER_UA,
            "Origin": "https://amisapp.misa.vn",
            "Referer": "https://amisapp.misa.vn/",
            "Accept": "application/json, text/plain, */*",
            "Host": "amisapp.misa.vn",
            "TenantID": "039c3227-6ba8-49ba-93f5-bde3e8e1f533",
        }

        session = requests.Session()
        r1 = session.post(login_url, json=login_payload, headers=login_headers)
        if r1.status_code != 200 or not r1.json().get("Success"):
            raise Exception("MISA actapp login failed (step 1)")

        cookies = session.cookies.get_dict()
        x_sessionid = cookies.get("x-sessionid")
        x_tenantid = cookies.get("x-tenantid")
        if not x_sessionid or not x_tenantid:
            raise Exception("Missing x-sessionid or x-tenantid cookie")

        token_url = "https://actapp.misa.vn/g1/api/auth/v1/account/login/misa_id"
        form_data = {
            "sid": x_sessionid,
            "dbid": _DB_ID,
            "tid": x_tenantid,
            "mid": _USER_ID,
        }
        r2 = session.post(token_url, data=form_data,
                          headers={"Content-Type": "application/x-www-form-urlencoded",
                                   "x-device": _X_DEVICE})
        j2 = r2.json()
        if not r2.ok or not j2.get("Success"):
            raise Exception("MISA actapp token failed (step 2)")

        return j2.get("Data", {}).get("AccessToken", {}).get("Token", "")

    # =====================================================================
    # Auth — CRM token (for product / category API)
    # =====================================================================
    def _get_crm_token(self):
        session = requests.Session()
        login_url = "https://amisapp.misa.vn/APIS/AuthenAPI/api/Account/login"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "PostmanRuntime/7.44.1",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br,zstd",
            "Connection": "keep-alive",
        }
        payload = {"PassWord": _LOGIN_PASSWORD, "UserName": _LOGIN_EMAIL}

        r = session.post(login_url, headers=headers, json=payload)
        if r.status_code != 200:
            raise Exception(f"CRM login failed: {r.status_code}")

        cookies = session.cookies.get_dict()
        x_sessionid = cookies.get("x-sessionid")
        x_tenantid = cookies.get("x-tenantid")
        if not x_sessionid or not x_tenantid:
            raise Exception("Missing required cookies from CRM login")

        cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
        cookie_header += "; x-login-from=basic"

        crm_r = session.get("https://amisapp.misa.vn/CRM/",
                            headers={"Cookie": cookie_header,
                                     "User-Agent": "PostmanRuntime/7.44.1"})
        if crm_r.status_code != 200:
            raise Exception(f"CRM page fetch failed: {crm_r.status_code}")

        m = re.search(r'"token"\s*:\s*"(?P<token>ey[\w\-\.]+)"', crm_r.text)
        if not m:
            raise Exception("Token not found in CRM HTML")
        return m.group("token")

    # =====================================================================
    # Header builders
    # =====================================================================
    def _actapp_headers(self, token):
        cookie_parts = [
            "cf_clearance=NnbIOcmJJX9cPSPMbP5wqaJ0d5N.6A_3p5pZRovrMFQ-1759224861-1.2.1.1-"
            "mkusGtWxAuLs4JRlxmV2YH1vRhP0HQWs5tESq958fx0lsCN3eF8sXpcmOedgMjsV"
            "yQCLvAm9T7jrH48r_FJw1aMpcjT0hLrln5xWqvcXBqTWh3N3QqIfNIX2LBTZp3T114"
            "YoGskvEAnWbJwHSvQErcIYAHvE7Hci8c9taXdPraO3bo2raQfMRp.pcIorYWIBM76ns"
            "EKGypx.9SuqRvQO8BevnN.gfSXOiM54MS5RhY8",
            f"tid={_TENANT_ID}",
            f"x-sessionid={_TENANT_ID.replace('-', '')}45649b79e2874e33b2d395ddb553ccfc",
            f"dbid={_DB_ID}",
            "env=g2",
        ]
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.9",
            "X-MISA-Context": json.dumps(_MISA_CONTEXT),
            "X-MISA-BranchID": _MISA_CONTEXT["BranchId"],
            "X-MISA-Language": "vi",
            "X-MISA-WorkingBook": "0",
            "X-Device": "f32be43d99071befa62cab0562947494",
            "Cookie": "; ".join(cookie_parts),
            "Referer": "https://actapp.misa.vn/app/SA/Return",
            "Origin": "https://actapp.misa.vn",
            "Host": "actapp.misa.vn",
            "Connection": "keep-alive",
            "User-Agent": _BROWSER_UA,
        }

    @staticmethod
    def _crm_hdrs(token):
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "vi,en-US;q=0.9,en;q=0.8",
            "Authorization": f"Bearer {token}",
            "CompanyCode": _COMPANY_CODE,
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }

    # =====================================================================
    # Dictionary helpers (unit, tax lookups)
    # =====================================================================
    def _get_all_dictionary_items(self, headers, field_name):
        url = (
            f"https://amisapp.misa.vn/crm/g2/api/business/Dictionary/"
            f"Details/Product/{field_name}/false/45/null/null"
        )
        get_h = {k: v for k, v in headers.items()
                 if k.lower() not in ('content-length', 'content-type')}
        try:
            r = self._retry_session().get(
                url, headers=get_h,
                params={"page": "null", "searchText": "", "isView": "true"},
                timeout=30)
            if r.ok and r.json().get("Success"):
                return r.json().get("Data", [])
        except Exception as e:
            _logger.warning("Dictionary lookup %s failed: %s", field_name, e)
        return []

    def _find_dictionary_item(self, headers, field_name, search_text):
        items = self._get_all_dictionary_items(headers, field_name)
        needle = str(search_text).strip().lower()
        for item in items:
            if str(item.get("text", "")).strip().lower() == needle:
                return item["id"], item["text"]
        return None, None

    def _find_tax_id(self, headers, amount, name=""):
        all_taxes = self._get_all_dictionary_items(headers, "TaxID")
        if not all_taxes:
            return "3", "10%"

        if amount == 0:
            upper = (name or "").upper()
            is_kct = any(x in upper for x in ("KCT", "KHÔNG CHỊU", "NO VAT"))
            for t in all_taxes:
                txt = t.get("text", "").upper()
                if is_kct and ("KCT" in txt or "KHÔNG CHỊU" in txt):
                    return str(t["id"]), t["text"]
                if not is_kct and "0%" in txt:
                    return str(t["id"]), t["text"]

        for t in all_taxes:
            nums = re.findall(r"[-+]?\d*\.\d+|\d+", t.get("text", ""))
            if nums:
                try:
                    if abs(float(nums[0]) - amount) < 0.001:
                        return str(t["id"]), t["text"]
                except:
                    continue
        return "3", "10%"

    # =====================================================================
    # Update-product payload builders
    # =====================================================================
    @staticmethod
    def _update_name_payload(misa_id, new_value, old_value):
        return {
            "FieldName": "ProductName",
            "PrimaryKeyName": "ID",
            "PrimaryKeyValue": str(misa_id),
            "Id": 2128,
            "Value": new_value,
            "OldValue": old_value,
            "TypeControl": 1,
            "FormLayoutID": 45,
            "LayoutCode": "Product",
            "Lable": "Tên hàng hóa",
            "Text": "Tên hàng hóa",
            "IsRequired": True,
            "IsNotZero": False,
            "IsSensitive": False,
            "IsUnique": False,
            "MaxLength": 500,
            "CustomRoundDigit": 2,
            "DecimalLength": 2,
            "ComparedValue": None,
            "ModuleType": None,
        }

    @staticmethod
    def _update_code_payload(misa_id, new_value, old_value):
        return {
            "FieldName": "ProductCode",
            "PrimaryKeyName": "ID",
            "PrimaryKeyValue": str(misa_id),
            "Id": 2127,
            "Value": new_value,
            "OldValue": old_value,
            "TypeControl": 10,
            "FormLayoutID": 45,
            "LayoutCode": "Product",
            "Lable": "Mã hàng hóa",
            "Text": "Mã hàng hóa",
            "IsRequired": False,
            "IsNotZero": False,
            "IsSensitive": False,
            "IsUnique": True,
            "MaxLength": 255,
            "CustomRoundDigit": 2,
            "DecimalLength": 2,
            "ComparedValue": None,
            "ModuleType": None,
        }

    @staticmethod
    def _empty_serial_row(sort_order):
        return {
            "SortOrder": sort_order,
            "TableName": "product_detail_serial_type",
            "DisplayName": None, "IsAllowDupplicate": None, "ID": None,
            "MISAEntityState": 1, "AsyncID": "", "OwnerID": "",
            "PromotionMasterRowID": "", "PromotionRowID": "",
            "ProductSetID": "", "ProductSetMasterID": "",
            "ProductInSetMasterID": "", "IsSetProduct": "",
            "IsChildProduct": "", "ProductIDInSet": "",
            "ExcludeCurrentRecord": "", "ExchangeID": 0,
            "IsExchangeProduct": None, "ExchangePoint": 0,
            "TotalAmountBasedUPriceAndDATax": False,
            "AmountBasedOnPriceAfterTax": False,
        }

    # =====================================================================
    # Product — search
    # =====================================================================
    def search_product(self, name=None, code=None, limit=20):
        if not name and not code:
            raise Exception("Cần truyền 'name' hoặc 'code'")

        token = self._get_crm_token()
        headers = self._crm_hdrs(token)
        headers.update({"LayoutCode": "product", "X-Misa-Language": "vi-VN"})

        url = "https://amisapp.misa.vn/crm/g1/api/business/Product/Grid"

        def _filter_block(field, display, value):
            return {
                "Value": value.strip(), "IsDefaultFilter": False,
                "IsCustomField": False, "IsRelatedField": False,
                "ModuleRelated": "", "FromFilterCustom": False,
                "ValueDisplayText": "", "isValueDateNumber": False,
                "IsSearchModule": False, "ConfigDisplayRelatedField": "",
                "ConfigSubDisplayRelatedField": "",
                "ConfigSearchField": [], "ConfigUrlCbx": "",
                "FilterObjects": [], "dataOperator": [],
                "IsProductCategory": False, "SelectedDataList": [],
                "IsCustomTypeDecimalDigits": False, "IsFromFormula": False,
                "Operator": 1, "Addition": 1,
                "Property": field, "InputType": 1, "FieldType": 0,
                "FieldName": field,
                "OperatorBeforeDetectChanges": 1, "InputTypeOrigin": 1,
                "DisplayField": display, "DisplayOperator": "Chứa",
                "DisplayValue": value.strip(), "ValueOrigin": value.strip(),
            }

        filters = []
        if name:
            filters.append(_filter_block("ProductName", "Tên hàng hóa", name))
        if code:
            filters.append(_filter_block("ProductCode", "Mã hàng hóa", code))

        payload = {
            "Columns": (
                "SUQsUHJvZHVjdENvZGUsUHJvZHVjdE5hbWUsUHJvZHVjdENhdGVnb3J5"
                "SUQsUHJvZHVjdENhdGVnb3J5SURUZXh0LFVzYWdlVW5pdElELFVzYWdl"
                "VW5pdElEVGV4dCxVbml0UHJpY2UsVGF4SUQsVGF4SURUZXh0LERlZmF1"
                "bHRTdG9ja0lELERlZmF1bHRTdG9ja0lEVGV4dCxGb3JtTGF5b3V0SUQs"
                "Rm9ybUxheW91dElEVGV4dCxPd25lcklELE93bmVySURUZXh0LElzU3lz"
                "dGVtLEF2YXRhcg=="
            ),
            "Sorts": [{"SortBy": "ModifiedDate", "Type": 0, "SortDirection": 1}],
            "Start": 0, "Page": 1, "PageSize": limit,
            "Filters": filters, "Formula": "",
            "LayoutCode": "Product", "DefaultTotal": True,
            "IsMappingData": False, "MappingValueObject": {},
            "IsApproved": False, "CustomPagingData": {},
            "IsUsedELTS": True, "ListGmailPage": [],
            "ListFacebookPage": {}, "IsListPaging": True,
            "IsGetCache": True, "IsCheckInactive": False,
            "IsConverted": False, "SessionID": str(uuid.uuid4()),
            "LayoutCodeCheckPermission": "Product",
            "AISearchKeyword": "",
        }

        _logger.info("🔎 [MISA] search_product name=%s code=%s", name, code)
        session = self._retry_session()
        res = session.post(url, headers=headers, json=payload, timeout=30)
        res_json = res.json()

        if not res_json.get("Success"):
            msg = res_json.get("UserMessage") or res.text[:200]
            raise Exception(f"MISA Search Failed: {msg}")

        return [
            {
                "misa_id": p.get("ID") or p.get("ProductID"),
                "code": p.get("ProductCode"),
                "name": p.get("ProductName"),
                "price": p.get("UnitPrice") or 0,
                "cost": p.get("PurchasedPrice") or 0,
                "unit": p.get("UsageUnitIDText"),
                "category": p.get("ProductCategoryIDText"),
                "tax": p.get("TaxIDText"),
                "type": p.get("ProductPropertiesIDText"),
                "active": p.get("Active", True),
            }
            for p in (res_json.get("Data") or [])
        ]

    # =====================================================================
    # Product — create
    # =====================================================================
    def create_product(self, code, name, price=0, price_pu=0,
                       tax_percent=10, unit_name='Cái',
                       category_name='Hàng hóa', product_type='goods',
                       cat_id=None):
        token = self._get_crm_token()
        headers = self._crm_hdrs(token)
        headers.update({"LayoutCode": "product", "X-Misa-Language": "vi-VN"})

        # resolve category name from ID
        if cat_id:
            cat_name_resolved = self.get_category_name(cat_id)
            if cat_name_resolved and cat_name_resolved != str(cat_id):
                category_name = cat_name_resolved

        # resolve unit
        unit_id, unit_text = self._find_dictionary_item(
            headers, "UsageUnitID", unit_name)
        if not unit_id:
            unit_id, unit_text = 4, "Cái"

        # resolve tax
        tax_id, tax_text = self._find_tax_id(headers, float(tax_percent))

        is_service = product_type in ('service', 'dịch vụ')
        prop_id = 2 if is_service else 1
        prop_text = "Dịch vụ" if is_service else "Hàng hóa"
        price_val = float(price)

        payload = {
            "ProductCode": code,
            "ProductName": name,
            "ProductCategoryID": cat_id,
            "ProductCategoryIDText": category_name if cat_id != 23 else "Hàng hóa",
            "UsageUnitID": unit_id,
            "UsageUnitIDText": unit_text,
            "ProductPropertiesID": prop_id,
            "ProductPropertiesIDText": prop_text,
            "TaxID": str(tax_id),
            "TaxIDText": tax_text,
            "UnitPrice": price_val,
            "UnitPriceFixed": price_val,
            "PurchasedPrice": 0,
            "MISAEntityState": 1,
            "Active": True, "Inactive": False, "IsPublic": False,
            "FormLayoutID": 45, "FormLayoutIDText": "Mẫu tiêu chuẩn",
            "IsFollowSerialNumber": False,
            "IsUseTax": False, "PriceAfterTax": False,
            "Fields": [], "FieldsCustom": [],
            "DefaultStockID": "29",
            "DefaultStockIDText": "HLV",
            "DataCustom": {
                "CustomField13": None, "CustomField13Text": "",
                "CustomField14": None, "CustomField15": None,
                "CustomField16": int(price_val), "Avatar": "",
            },
            "CustomTables": [
                {
                    "DataFields": [], "Summary": {}, "Data": [],
                    "OldData": [], "SummaryFields": [],
                    "GroupBoxText": "Thông tin đơn vị chuyển đổi",
                    "IsRequired": False,
                    "ParentIDKey": "ProductID",
                    "TableName": "product_conversion_unit",
                    "IsProductChange": False,
                },
                {
                    "DataFields": [], "Summary": {},
                    "Data": [self._empty_serial_row(i) for i in range(1, 6)],
                    "OldData": [self._empty_serial_row(i) for i in range(1, 6)],
                    "SummaryFields": [],
                    "GroupBoxText": "Thông tin mã quy cách",
                    "IsRequired": False,
                    "ParentIDKey": "ProductID",
                    "TableName": "product_detail_serial_type",
                    "IsProductChange": True,
                },
            ],
            "IsProductChange": False,
            "IsMultiCurrency": False,
            "FormModeState": 1,
            "IsGetFieldFormLayout": True,
            "IsSetProduct": "\u0000",
        }

        url = "https://amisapp.misa.vn/crm/g2/api/business/Product"
        _logger.info("📤 [MISA] create_product code=%s", code)

        session = self._retry_session()
        res = session.post(url, headers=headers, json=payload, timeout=30)
        res_json = res.json()

        if not res_json.get("Success"):
            err = res_json.get("UserMessage")
            val_info = res_json.get("ValidateInfo", [])
            if val_info:
                err = ", ".join(v.get("ErrorMessage", "") for v in val_info)
            raise Exception(f"MISA Refused: {err}")

        misa_id = self._parse_misa_id(res_json, code, headers)
        if not misa_id:
            raise Exception("MISA OK nhưng không trả ID")

        # --- Sync to Odoo ---
        self._sync_product_to_odoo(
            code, name, price, price_pu,
            product_type, cat_id, unit_name, tax_percent)
        return misa_id

    def _parse_misa_id(self, res_json, code, headers):
        data = res_json.get("Data")
        if isinstance(data, int):
            return str(data)
        if isinstance(data, str) and data:
            return data
        if isinstance(data, dict):
            return data.get("ProductID") or data.get("ID")

        # Fallback: search by code
        url = "https://amisapp.misa.vn/crm/g2/api/business/Product/DataSubPaging"
        fb_payload = {
            "Page": 1, "PageSize": 1,
            "Filters": [{"FieldName": "ProductCode",
                         "Operator": 1, "OperandType": 0,
                         "Value": code}],
        }
        try:
            r = requests.post(url, headers=headers,
                              json=fb_payload, timeout=10)
            d = r.json()
            if d.get("Success") and d.get("Data"):
                return str(d["Data"][0].get("ProductID"))
        except:
            pass
        return None

    def _sync_product_to_odoo(self, code, name, price, price_pu,
                              product_type, cat_id, unit_name, tax_percent):
        """Best-effort sync to Odoo product.template after MISA creation."""
        try:
            pos_categ = False
            if cat_id:
                pos_categ = self.env['pos.category'].sudo().search(
                    [('x_misa_id', '=', int(cat_id))], limit=1)

            uom_id = False
            if unit_name:
                found = self.env['uom.uom'].sudo().search(
                    [('name', '=', unit_name)], limit=1)
                if found:
                    uom_id = found.id

            tax_ids = []
            if tax_percent:
                try:
                    pct = float(tax_percent)
                    tax = self.env['account.tax'].sudo().search([
                        ('type_tax_use', '=', 'sale'),
                        ('amount', '=', pct),
                        ('company_id', '=', self.env.company.id),
                    ], limit=1)
                    if tax:
                        tax_ids = [(6, 0, [tax.id])]
                except:
                    pass

            is_goods = str(product_type).lower() == 'goods'
            vals = {
                'name': name,
                'list_price': price,
                'standard_price': price_pu,
                'type': 'consu' if is_goods else 'service',
                'is_storable': is_goods,
                'available_in_pos': True,
            }
            if tax_ids:
                vals['taxes_id'] = tax_ids
            if pos_categ:
                vals['pos_categ_ids'] = [(6, 0, [pos_categ.id])]
            if uom_id:
                vals['uom_id'] = uom_id
                vals['uom_po_id'] = uom_id

            existing = self.env['product.template'].sudo().search(
                [('default_code', '=', code)], limit=1)
            if not existing:
                vals['default_code'] = code
                self.env['product.template'].sudo().create(vals)
            else:
                existing.sudo().write(vals)
        except Exception as e:
            _logger.error("Odoo sync failed: %s", e)

    # =====================================================================
    # Product — update field
    # =====================================================================
    def update_product_field(self, misa_id, field_type, new_value, old_value):
        if not misa_id:
            return False

        token = self._get_crm_token()
        headers = self._crm_hdrs(token)
        headers.update({"LayoutCode": "product", "X-Misa-Language": "vi-VN"})

        if field_type == 'name':
            payload = self._update_name_payload(misa_id, new_value, old_value)
        elif field_type == 'code':
            payload = self._update_code_payload(misa_id, new_value, old_value)
        else:
            return False

        url = "https://amisapp.misa.vn/crm/g2/api/business/product"
        try:
            res = self._retry_session().put(
                url, headers=headers, json=payload, timeout=20)
            rj = res.json()
            if res.ok and rj.get("Success"):
                _logger.info("✅ Updated %s for MISA ID %s", field_type, misa_id)
                return True
            _logger.warning("⚠️ Update %s failed: %s", field_type, res.text)
            return False
        except Exception as e:
            _logger.error("❌ Update %s error: %s", field_type, e)
            return False

    # =====================================================================
    # Category — get name by ID
    # =====================================================================
    def get_category_name(self, cat_id):
        if not cat_id:
            return None

        token = self._get_crm_token()
        headers = self._crm_hdrs(token)

        url = ("https://amisapp.misa.vn/crm/g1/api/business/"
               "ProductCategory/FormDataNew/ProductCategory/46/4")
        payload = {
            "ID": str(cat_id),
            "MISAEntityState": 2,
            "ActiveLayoutCode": None,
            "CustomDicData": None,
        }
        try:
            post_h = headers.copy()
            post_h['layoutcode'] = 'productcategory'
            for k in ('content-length', 'Content-Length'):
                post_h.pop(k, None)

            res = self._retry_session().post(
                url, headers=post_h, json=payload, timeout=20)
            if res.ok:
                data = res.json()
                if data.get("Success"):
                    name = (data.get("Data", {})
                            .get("CurrentData", {})
                            .get("ProductCategoryName"))
                    if name:
                        return str(name).strip()
        except Exception as e:
            _logger.error("get_category_name error: %s", e)
        return None

    # =====================================================================
    # Category — search by name
    # =====================================================================
    def search_category_by_name(self, name):
        if not name:
            return None

        clean = str(name).strip().lower()
        token = self._get_crm_token()
        headers = self._crm_hdrs(token)
        session = self._retry_session()

        # Strategy 1: Tree API
        try:
            get_h = {k: v for k, v in headers.items()
                     if k.lower() not in ('content-length', 'content-type')}
            url_tree = ("https://amisapp.misa.vn/crm/g1/api/business/"
                        "ProductCategory/tree/0/false")
            res = session.get(url_tree, headers=get_h, timeout=20)
            if res.ok and res.json().get("Success"):
                raw = res.json().get("Data")
                nodes = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(nodes, list):
                    def _walk(lst):
                        for n in lst:
                            n_name = str(n.get("ProductCategoryName") or "").strip().lower()
                            if n_name == clean:
                                return n.get("ID")
                            children = n.get("Children")
                            if children and isinstance(children, list):
                                found = _walk(children)
                                if found:
                                    return found
                        return None
                    found_id = _walk(nodes)
                    if found_id:
                        return found_id
        except Exception as e:
            _logger.warning("Tree search failed: %s", e)

        # Strategy 2: Grid pagination
        url_grid = "https://amisapp.misa.vn/crm/g2/api/business/ProductCategory/grid"
        page, page_size = 1, 200
        while page <= 50:
            grid_payload = {
                "Filters": [], "page": page, "pageSize": page_size,
                "Columns": "ProductCategoryID,ProductCategoryName",
                "layoutCode": "ProductCategory",
            }
            try:
                res = session.post(url_grid, headers=headers,
                                   json=grid_payload, timeout=20)
                if not res.ok or not res.json().get("Success"):
                    break
                items = res.json().get("Data", [])
                if not items:
                    break
                for item in items:
                    c_name = str(item.get("ProductCategoryName") or "").strip().lower()
                    if c_name == clean:
                        return item.get("ProductCategoryID") or item.get("ID")
                if len(items) < page_size:
                    break
                page += 1
            except:
                break
        return None

    # =====================================================================
    # Purchase — search voucher
    # =====================================================================
    def search_purchase_voucher(self, journal_memo, limit=20):
        if not journal_memo:
            raise Exception("Cần truyền 'journal_memo'")

        token = self._get_actapp_token()
        headers = self._actapp_headers(token)

        url = "https://actapp.misa.vn/g2/api/pu/v1/pu_list/paging_filter_v2"
        terms = [s.strip() for s in journal_memo.split(',') if s.strip()]
        if not terms:
            return []

        date_to = datetime.utcnow()
        date_from = date_to - timedelta(days=365)
        session = self._retry_session()

        all_results = []
        seen = set()

        for val in terms:
            _logger.info("🔎 [MISA] search_purchase_voucher term=%s", val)
            pv_payload = {
                "sort": json.dumps([
                    {"property": 3654, "desc": True, "data_type": 3, "operand": 1},
                    {"property": 3972, "desc": True, "data_type": 3, "operand": 1},
                    {"property": 4018, "desc": True, "data_type": 1, "operand": 1},
                ]),
                "filter": [
                    {"property": 3654,
                     "value": date_from.strftime("%Y-%m-%dT%H:%M:%S.00Z"),
                     "operator": 10, "operand": 1, "data_type": 3},
                    {"property": 3654,
                     "value": date_to.strftime("%Y-%m-%dT%H:%M:%S.00Z"),
                     "operator": 12, "operand": 1, "data_type": 3},
                ],
                "customFilter": [{
                    "property": 4018, "value": val,
                    "operator": 1, "operand": 1, "data_type": 1,
                    "childrens": [
                        {"property": 2189, "value": val, "operator": 1,
                         "operand": 2, "data_type": 1},
                        {"property": 57, "value": val, "operator": 1,
                         "operand": 2, "data_type": 1},
                        {"property": 2656, "value": val, "operator": 1,
                         "operand": 2, "data_type": 1},
                        {"property": 4029, "value": val, "operator": 1,
                         "operand": 2},
                    ],
                }],
                "pageIndex": 1,
                "pageSize": int(limit),
                "view": 40,
                "useSp": False,
                "loadMode": 2,
                "summaryColumns": [5080, 5730, 5128, 5059],
            }
            try:
                res = session.post(url, headers=headers,
                                   json=pv_payload, timeout=30)
                if res.status_code != 200:
                    _logger.error("Purchase search HTTP %s: %s",
                                  res.status_code, res.text)
                    continue
                data = res.json()
                if not data.get("Success"):
                    _logger.warning("MISA refused for '%s': %s", val, data)
                    continue
                for item in data.get("Data", {}).get("PageData", []):
                    refid = item.get("refid")
                    if refid and refid not in seen:
                        seen.add(refid)
                        all_results.append(item)
            except Exception as e:
                _logger.exception("Purchase search error for '%s': %s", val, e)

        _logger.info("✅ [MISA] purchase search: %d results for %d terms",
                      len(all_results), len(terms))
        return all_results
