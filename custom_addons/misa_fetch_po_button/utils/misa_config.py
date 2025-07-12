from odoo import models
import json

class MisaConfig(models.AbstractModel):
    _name = 'misa.config'
    _description = 'MISA Configuration'

    def get_misa_context(self):
        """Trả về context cấu hình cho MISA API."""
        return  {"TenantId":"47ab503b-99d5-4eb8-aa11-24927abb3585","TenantCode":"3R2PY2F4","DatabaseId":"f4b18d63-6c99-4a53-b974-f6208e84fced","BranchId":"53a073a0-5381-4493-820f-51ea32ebe990","WorkingBook":0,"Language":"vi","IncludeDependentBranch":"False","SessionId":"ss1547cc69a995421e91347736dabe6cb9.693017cdc24074e96e4756afbf2b6ab6.f4b18d636c994a53b974f6208e84fced.638877626393411146","DBType":1,"AuthType":0,"AmisSessionId":"NAA3AGEAYgA1ADAAMwBiADkAOQBkADUANABlAGIAOABhAGEAMQAxADIANAA5ADIANwBhAGIAYgAzADUAOAA1ADkAMgBiADgANABhADYAZgBiADYAZQBiADQANwBhADgAYQA0AGUAMgBhAGUAYgAzAGEAZQA2ADMAYgA0ADYAYwA=","HasAgent":False,"UserType":1,"art":1,"UserId":"1547cc69-a995-421e-9134-7736dabe6cb9","isc":False}
    def get_default_headers(self, access_token):
        """Trả về headers mặc định cho MISA API."""
        context = self.get_misa_context()
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-MISA-Context": json.dumps(self.get_misa_context()),  # Chuyển sang string nếu cần
            "X-MISA-BranchID": context['BranchId'],
            "X-MISA-Language": "vi",
            "X-MISA-WorkingBook": "0",
            "X-Device": "04aadfced5b04995ecfacb0a7da5c50c",
            "Host":"actapp.misa.vn",
            "Content-Length":"574",
            "Connection":"keep-alive"
            
        }
        
        
    def get_crm_header(self,token):
        return {
            "Accept": "application/json, text/plain, */*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language":"en-US,en;q=0.9,vi;q=0.8",
            "Authorization": f"Bearer {token}",
            "companycode":"3R2PY2F4",
            "connection":"keep-alive",
            "content-length:":"2448",
            "content-type:":"application/json",
            
        }
        
    def get_crm_sale_order_payload(self,date,page):
        return   {
        "Columns": "SUQsUmV2ZW51ZVN0YXR1c0lELFJldmVudWVTdGF0dXNJRFRleHQsU2FsZU9yZGVyTm8sU2FsZU9yZGVyTmFtZSxTYWxlT3JkZXJBbW91bnQsU2FsZU9yZGVyRGF0ZSxCb29rRGF0ZSxPd25lcklELE93bmVySURUZXh0LE9yZ2FuaXphdGlvblVuaXRJRCxPcmdhbml6YXRpb25Vbml0SURUZXh0LERlbGl2ZXJ5U3RhdHVzSUQsRGVsaXZlcnlTdGF0dXNJRFRleHQsUGF5U3RhdHVzSUQsUGF5U3RhdHVzSURUZXh0LEJpbGxpbmdDb3VudHJ5SUQsQmlsbGluZ0NvdW50cnlJRFRleHQsQmlsbGluZ1Byb3ZpbmNlSUQsQmlsbGluZ1Byb3ZpbmNlSURUZXh0LEJpbGxpbmdEaXN0cmljdElELEJpbGxpbmdEaXN0cmljdElEVGV4dCxCaWxsaW5nV2FyZElELEJpbGxpbmdXYXJkSURUZXh0LERlbGl2ZXJ5T3JkZXJOdW1iZXIsRm9ybUxheW91dElELEZvcm1MYXlvdXRJRFRleHQsSXNQYXJlbnRTYWxlT3JkZXIsT3Bwb3J0dW5pdHlJRCxPcHBvcnR1bml0eUlEVGV4dCxSb2xlT3duZXJJRCxJc1VzZUN1cnJlbmN5LEV4Y2hhbmdlUmF0ZSxQYXJlbnRJRCxQYXJlbnRJRFRleHQsUXVvdGVJRCxRdW90ZUlEVGV4dCxBY2NvdW50SUQsQWNjb3VudElEVGV4dCxDb250YWN0SUQsQ29udGFjdElEVGV4dCxFYXJuaW5nUG9pbnQsRXhjaGFuZ2VQb2ludCxQYWlkRGF0ZSxEZWxpdmVyeURhdGUsQXBwcm92ZWRTdGF0dXNJRCxUYWdJRCxUYWdJRFRleHQsRXhwZWN0ZWREZWxpdmVyeURhdGUsRGVsaXZlcnlQYXJ0bmVySUQsRGVsaXZlcnlQYXJ0bmVyU3RhdHVzSUQsRGVsaXZlcnlQYXJ0bmVyU3RhdHVzSURUZXh0LEVjb21tZXJjZUlELFByb2R1Y3Rpb25Db25maXJtYXRpb25TdGF0dXNJRCxQcm9kdWN0aW9uQ29uZmlybWF0aW9uU3RhdHVzSURUZXh0LFByb2R1Y3Rpb25EYXRl",
        "Sorts": [
            {
                "SortBy": "ModifiedDate",
                "Type": 0,
                "SortDirection": 1
            }
        ],
        "Start": 20,
        "Page": page * 20,
        "PageSize": 20,
        "Filters": [
            {
                "Value": "2025-07-10T17:00:00.000Z",
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
                "Operator": 11,
                "Addition": 1,
                "Property": "SaleOrderDate",
                "InputType": 7,
                "FieldType": 0,
                "FieldName": "SaleOrderDate",
                "OperatorBeforeDetectChanges": 11,
                "InputTypeOrigin": 7,
                "DisplayField": "Ngày đặt hàng",
                "DisplayOperator": "Là",
                "DisplayValue": "11/07/2025",
                "ValueOrigin": "2025-07-10T17:00:00.000Z"
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
        "SessionID": "5e9f0a14-286f-631d-8183-3fc80b5b0157",
        "LayoutCodeCheckPermission": "SaleOrder",
        "AISearchKeyword": ""
    }
        
        
    def get_crm_sale_order_detail_payload(id):
        
        return {
            "Columns": "SUQsU29ydE9yZGVyLFByb2R1Y3RJRCxQcm9kdWN0SURUZXh0LERlc2NyaXB0aW9uLERlc2NyaXB0aW9uUHJvZHVjdCxTdG9ja0lELFN0b2NrSURUZXh0LFVuaXRJRCxVbml0SURUZXh0LEFtb3VudCxTaGlwcGluZ0Ftb3VudCxQcmljZSxUb0N1cnJlbmN5LERpc2NvdW50UGVyY2VudCxEaXNjb3VudCxUYXhQZXJjZW50SUQsVGF4UGVyY2VudElEVGV4dCxUYXgsVG90YWwsU2FsZU9yZGVyUHJvZHVjdElELFNhbGVPcmRlclByb2R1Y3RJRFRleHQsUHJvbW90aW9uSUQsUHJvbW90aW9uSURUZXh0LElzUHJvbW90aW9uLElzU2V0UHJvZHVjdCxJc0NoaWxkUHJvZHVjdA==",
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