from odoo import models
import json
from datetime import datetime

class MisaConfig(models.AbstractModel):
    _name = 'misa.config'
    _description = 'MISA Configuration'

    def get_misa_context(self):
        """Trả về context cấu hình cho MISA API."""
        return  {"TenantId":"47ab503b-99d5-4eb8-aa11-24927abb3585","TenantCode":"3R2PY2F4","DatabaseId":"f4b18d63-6c99-4a53-b974-f6208e84fced","BranchId":"53a073a0-5381-4493-820f-51ea32ebe990","WorkingBook":0,"Language":"vi","IncludeDependentBranch":"False","SessionId":"ss1547cc69a995421e91347736dabe6cb9.693017cdc24074e96e4756afbf2b6ab6.f4b18d636c994a53b974f6208e84fced.638877626393411146","DBType":1,"AuthType":0,"AmisSessionId":"NAA3AGEAYgA1ADAAMwBiADkAOQBkADUANABlAGIAOABhAGEAMQAxADIANAA5ADIANwBhAGIAYgAzADUAOAA1ADkAMgBiADgANABhADYAZgBiADYAZQBiADQANwBhADgAYQA0AGUAMgBhAGUAYgAzAGEAZQA2ADMAYgA0ADYAYwA=","HasAgent":False,"UserType":1,"art":1,"UserId":"1547cc69-a995-421e-9134-7736dabe6cb9","isc":False}
    
    def get_default_headers(self, access_token):
        """Trả về headers mặc định cho MISA API với ĐẦY ĐỦ context và cookies.
        
        ⚠️ QUAN TRỌNG: API detail_full CẦN đủ headers này mới không timeout:
        - Authorization: Bearer token
        - X-MISA-Context: Context đầy đủ (TenantId, BranchId, DatabaseId, SessionId, UserId...)
        - X-Device: Device ID
        - Cookie: Session cookies (tid, x-sessionid, dbid, env, cf_clearance)
        - Referer/Origin: Để backend biết request từ UI chính thức
        """
        context = self.get_misa_context()
        
        # Build cookie string từ session hiện tại
        # Note: Các giá trị này cần lấy từ browser hoặc login flow thực tế
        cookie_parts = [
            "cf_clearance=NnbIOcmJJX9cPSPMbP5wqaJ0d5N.6A_3p5pZRovrMFQ-1759224861-1.2.1.1-mkusGtWxAuLs4JRlxmV2YH1vRhP0HQWs5tESq958fx0lsCN3eF8sXpcmOedgMjsVyQCLvAm9T7jrH48r_FJw1aMpcjT0hLrln5xWqvcXBqTWh3N3QqIfNIX2LBTZp3T114YoGskvEAnWbJwHSvQErcIYAHvE7Hci8c9taXdPraO3bo2raQfMRp.pcIorYWIBM76nsEKGypx.9SuqRvQO8BevnN.gfSXOiM54MS5RhY8",
            "tid=47ab503b-99d5-4eb8-aa11-24927abb3585",
            "x-sessionid=47ab503b99d54eb8aa1124927abb358545649b79e2874e33b2d395ddb553ccfc",
            "dbid=f4b18d63-6c99-4a53-b974-f6208e84fced",
            "env=g2",
            f"env_f4b18d63_6c99_4a53_b974_f6208e84fced_10_30_2025=g2",
        ]
        
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.9",
            "X-MISA-Context": json.dumps(context),  # Context đầy đủ
            "X-MISA-BranchID": context['BranchId'],
            "X-MISA-Language": "vi",
            "X-MISA-WorkingBook": "0",
            "X-Device": "f32be43d99071befa62cab0562947494",  # Device ID từ browser
            "Cookie": "; ".join(cookie_parts),  # ← QUAN TRỌNG: Cookies session
            "Referer": "https://actapp.misa.vn/app/SA/Return",
            "Origin": "https://actapp.misa.vn",
            "Host": "actapp.misa.vn",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0"
        }
    def get_purchase_header(self, access_token):
        """Alias để tương thích ngược với code cũ gọi purchase header."""
        return self.get_default_headers(access_token)
    
        # header của list order
    def get_crm_header(self,token):
        return {
            "Accept": "application/json, text/plain, */*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language":"en-US,en;q=0.9,vi;q=0.8",
            "Authorization": f"Bearer {token}",
            "companycode":"3R2PY2F4",
            "connection":"keep-alive",
            "content-length":"2448",
            "content-type":"application/json",
            
        }
        # payload listorder
    def get_crm_sale_order_payload(self, start_date, end_date, page):
        page_size = 20
        start = (page - 1) * page_size if page > 0 else 0

        def parse_date(date):
            if isinstance(date, str):
                try:
                    return datetime.fromisoformat(date)
                except ValueError:
                    raise ValueError("Date string must be ISO format: 'YYYY-MM-DDTHH:MM:SS'")
            elif isinstance(date, datetime):
                return date
            else:
                raise TypeError("Date must be a string or datetime object")

        start_obj = parse_date(start_date)
        end_obj = parse_date(end_date)

        # Format ngày theo chuẩn
        iso_start = start_obj.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        iso_end = end_obj.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        display_value = f"{start_obj.strftime('%d/%m/%Y')} - {end_obj.strftime('%d/%m/%Y')}"
        value_json = f'{{"FirstVal":"{iso_start}","SecondVal":"{iso_end}"}}'

        return {
            "Columns": "SUQsUmV2ZW51ZVN0YXR1c0lELFJldmVudWVTdGF0dXNJRFRleHQsU2FsZU9yZGVyTm8sU2FsZU9yZGVyTmFtZSxTYWxlT3JkZXJBbW91bnQsU2FsZU9yZGVyRGF0ZSxCb29rRGF0ZSxPd25lcklELE93bmVySURUZXh0LE9yZ2FuaXphdGlvblVuaXRJRCxPcmdhbml6YXRpb25Vbml0SURUZXh0LERlbGl2ZXJ5U3RhdHVzSUQsRGVsaXZlcnlTdGF0dXNJRFRleHQsUGF5U3RhdHVzSUQsUGF5U3RhdHVzSURUZXh0LEJpbGxpbmdDb3VudHJ5SUQsQmlsbGluZ0NvdW50cnlJRFRleHQsQmlsbGluZ1Byb3ZpbmNlSUQsQmlsbGluZ1Byb3ZpbmNlSURUZXh0LEJpbGxpbmdEaXN0cmljdElELEJpbGxpbmdEaXN0cmljdElEVGV4dCxCaWxsaW5nV2FyZElELEJpbGxpbmdXYXJkSURUZXh0LERlbGl2ZXJ5T3JkZXJOdW1iZXIsRm9ybUxheW91dElELEZvcm1MYXlvdXRJRFRleHQsSXNQYXJlbnRTYWxlT3JkZXIsT3Bwb3J0dW5pdHlJRCxPcHBvcnR1bml0eUlEVGV4dCxSb2xlT3duZXJJRCxJc1VzZUN1cnJlbmN5LEV4Y2hhbmdlUmF0ZSxQYXJlbnRJRCxQYXJlbnRJRFRleHQsUXVvdGVJRCxRdW90ZUlEVGV4dCxBY2NvdW50SUQsQWNjb3VudElEVGV4dCxDb250YWN0SUQsQ29udGFjdElEVGV4dCxFYXJuaW5nUG9pbnQsRXhjaGFuZ2VQb2ludCxQYWlkRGF0ZSxEZWxpdmVyeURhdGUsQXBwcm92ZWRTdGF0dXNJRCxUYWdJRCxUYWdJRFRleHQsRXhwZWN0ZWREZWxpdmVyeURhdGUsRGVsaXZlcnlQYXJ0bmVySUQsRGVsaXZlcnlQYXJ0bmVyU3RhdHVzSUQsRGVsaXZlcnlQYXJ0bmVyU3RhdHVzSURUZXh0LEVjb21tZXJjZUlELFByb2R1Y3Rpb25Db25maXJtYXRpb25TdGF0dXNJRCxQcm9kdWN0aW9uQ29uZmlybWF0aW9uU3RhdHVzSURUZXh0LFByb2R1Y3Rpb25EYXRlLFBob25l",
            # giữ nguyên danh sách column như bạn đã có
            "Sorts": [
                {
                    "SortBy": "ModifiedDate",
                    "Type": 0,
                    "SortDirection": 1
                }
            ],
            "Start": start,
            "Page": page,
            "PageSize": page_size,
            "CustomColumns":"Q3VzdG9tRmllbGQyMw==",
            "Filters": [
                {
                    "Value": value_json,
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
                    "Operator": 29,
                    "Addition": 1,
                    "Property": "SaleOrderDate",
                    "InputType": 7,
                    "FieldType": 0,
                    "FieldName": "SaleOrderDate",
                    "OperatorBeforeDetectChanges": 29,
                    "InputTypeOrigin": 7,
                    "Value1": iso_start,
                    "Value2": iso_end,
                    "DisplayField": "Ngày đặt hàng",
                    "DisplayOperator": "Trong khoảng",
                    "DisplayValue": display_value,
                    "ValueOrigin": value_json
                }
            ],
            "Formula": "",
            "LayoutCode": "SaleOrder",
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
            "SessionID": "864e2811-5edd-5ccc-6b85-178b59007e93",
            "LayoutCodeCheckPermission": "SaleOrder",
            "AISearchKeyword": ""
        }
        
    def get_crm_sale_order_detail_payload(self,id):
        
        return {
            "Columns": "SUQsU29ydE9yZGVyLFByb2R1Y3RJRCxQcm9kdWN0SURUZXh0LFN0b2NrSUQsU3RvY2tJRFRleHQsRGVzY3JpcHRpb24sRGVzY3JpcHRpb25Qcm9kdWN0LEN1c3RvbUZpZWxkMixDdXN0b21GaWVsZDQsVW5pdElELFVuaXRJRFRleHQsQW1vdW50LFNoaXBwaW5nQW1vdW50LFByaWNlQWZ0ZXJUYXgsUHJpY2UsVG9DdXJyZW5jeSxEaXNjb3VudFBlcmNlbnQsRGlzY291bnQsVGF4UGVyY2VudElELFRheFBlcmNlbnRJRFRleHQsVGF4LFRvdGFsLFByb21vdGlvbklELFByb21vdGlvbklEVGV4dCxDdXN0b21GaWVsZDEsSXNTZXRQcm9kdWN0LElzQ2hpbGRQcm9kdWN0",
            "Sorts": [],
            "Start": 0,
            "Page": 1,
            "PageSize": 20,
            "Filters": [],
            "DefaultTotal": True,
            "IsMappingData": False,
            "MappingValueObject": {
                "MasterID": id,
                "TableName": "sale_order_product",
                "MasterKey": "CustomID",
                "SumColumn": ""
            },
            "IsApproved": False,
            "CustomPagingData": {
                "SubFormConfig": {
                    "ColumnFieldSubForm": "",
                    "ColumnAggregateSubForm": "TotalSummary,TaxSummary,DiscountAfterTaxSummary,DiscountSummary,ToCurrencySummary,ShippingAmountSummary,AmountSummary,DiscountOverall,DiscountOverallOC,TaxOverall,TaxOverallOC,TotalOverall,TotalOverallOC,IsDiscountDirectlyOverall,DiscountPercentOverall,TaxPercentOverallID,ProducedQuantitySummary,ToCurrencyAfterDiscountSummary,ToCurrencyOCAfterDiscountSummary,TotalSummaryOC,TaxSummaryOC,DiscountSummaryOC,ToCurrencySummaryOC,UsageUnitAmountSummary,PromotionOverAllID,IsPromotionDiscountOverAll",
                    "TableName": "sale_order_product",
                    "IsSystem": True,
                    "ParentIDKey": "CustomID",
                    "IsBringSerialType": False,
                    "AggregateField": [
                    
                    ]
                }
            },
            "IsUsedELTS": True,
            "ListGmailPage": [],
            "ListFacebookPage": {},
            "IsListPaging": True,
            "IsGetCache": True,
            "IsCheckInactive": False,
            "IsConverted": False,
            "SessionID": "7781e4ab-f17a-dda6-0af2-c470ee96a470",
            "AISearchKeyword": ""
        }

    def get_invoice_request_payload(self, request_no):
        import datetime
        now_iso = datetime.datetime.utcnow().isoformat() + "Z"
        return {
            "sort": "[{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":4008,\"desc\":true,\"data_type\":1,\"operand\":1}]",
            "filter": [
                { "property": 3972, "value": "2025-12-31T17:00:00.00Z", "operator": 10, "operand": 1, "data_type": 3 },
                { "property": 3972, "value": now_iso, "operator": 12, "operand": 1, "data_type": 3 }
            ],
            "customFilter": [{
                "property": 4008, "value": request_no, "operator": 1, "operand": 1, "childrens": [
                    { "property": 4177, "value": request_no, "operator": 1, "operand": 2, "data_type": 1 },
                    { "property": 3342, "value": request_no, "operator": 1, "operand": 2, "data_type": 1 },
                    { "property": 57, "value": request_no, "operator": 1, "operand": 2, "data_type": 1 },
                    { "property": 2656, "value": request_no, "operator": 1, "operand": 2, "data_type": 1 },
                    { "property": 2189, "value": request_no, "operator": 1, "operand": 2, "data_type": 1 },
                    { "property": 5150, "value": request_no, "operator": 1, "operand": 2, "data_type": 1 },
                    { "property": 3295, "value": request_no, "operator": 1, "operand": 2, "data_type": 1 }
                ], "data_type": 1
            }],
            "pageIndex": 1, "pageSize": 10, "useSp": False, "view": 65, "summaryColumns": [5127, 5069, 5142, 5047]
        }

    def get_invoice_full_search_payload(self, target_customer):
        import datetime
        now_iso = datetime.datetime.utcnow().isoformat() + "Z"
        return {
            "sort": "[{\"property\":2127,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":2189,\"desc\":true,\"data_type\":1,\"operand\":1},{\"property\":1472,\"desc\":true,\"data_type\":4,\"operand\":1},{\"property\":1058,\"desc\":true,\"data_type\":3,\"operand\":1}]",
            "filter": [
                { "property": 2127, "value": "2025-12-31T17:00:00.00Z", "operator": 10, "operand": 1, "data_type": 3 },
                { "property": 2127, "value": now_iso, "operator": 12, "operand": 1, "data_type": 3 }
            ],
            "customFilter": [
                { "property": 57, "value": target_customer, "operator": 1, "operand": 1, "childrens": [], "data_type": 1 },
                { "property": 1457, "value": None, "operator": 15, "operand": 1, "childrens": [
                    { "property": 1457, "value": None, "operator": 16, "operand": 2, "childrens": [
                        { "property": 3811, "value": 1, "operator": 10, "operand": 1, "data_type": 4 }
                    ]}
                ]}
            ],
            "pageIndex": 1, "pageSize": 200, "useSp": False, "view": 41, "summaryColumns": [5126, 5068, 5141, 5039], "loadMode": 2
        }

    def get_invoice_preview_payload(self, refid, date):
        """Payload to fetch a preview PDF link for a specific invoice."""
        return [{
            "RefID": refid, "inv_refid": refid, "RefType": 3560, "invdate": date,"business_area":0,
            "invtemplateno": "1", "invseries": "1C26TLV", "InvoiceTemplateID": "5d966b18-1ca1-404a-af7f-6c1edddf15ce"
        }]

    def get_misa_update_product_name_payload(self, misa_id, new_value, old_value):
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
            "ModuleType": None
        }

    def get_misa_update_product_code_payload(self, misa_id, new_value, old_value):
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
            "ModuleType": None
        }

    def get_misa_update_product_description_payload(self, misa_id, new_value, old_value):
        return {
            "FieldName": "Description",
            "PrimaryKeyName": "ID",
            "PrimaryKeyValue": str(misa_id),
            "Id": 2130,
            "Value": new_value,
            "OldValue": old_value,
            "TypeControl": 2,
            "FormLayoutID": 45,
            "LayoutCode": "Product",
            "Lable": "Mô tả",
            "Text": "Mô tả",
            "IsRequired": False,
            "IsNotZero": False,
            "IsSensitive": False,
            "IsUnique": False,
            "MaxLength": 4000,
            "CustomRoundDigit": 2,
            "DecimalLength": 2,
            "ComparedValue": None,
            "ModuleType": None
        }
