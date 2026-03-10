#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script test MISA API - Chạy standalone từ terminal
Không cần Odoo shell
"""

import requests
import json
import copy
from urllib.parse import quote

# ========== CONFIG ==========
MISA_GRID_URL = "https://amisapp.misa.vn/crm/g1/api/business/SaleOrder/Grid"

PAYLOAD_TEMPLATE = {
    "Columns": "SUQsUmV2ZW51ZVN0YXR1c0lELFJldmVudWVTdGF0dXNJRFRleHQsQWNjb3VudElELEFjY291bnRJRFRleHQsU2FsZU9yZGVyTm8sU2FsZU9yZGVyTmFtZSxTYWxlT3JkZXJBbW91bnQsU2FsZU9yZGVyRGF0ZSxCb29rRGF0ZSxPd25lcklELE93bmVySURUZXh0LE9yZ2FuaXphdGlvblVuaXRJRCxPcmdhbml6YXRpb25Vbml0SURUZXh0LERlbGl2ZXJ5U3RhdHVzSUQsRGVsaXZlcnlTdGF0dXNJRFRleHQsUGF5U3RhdHVzSUQsUGF5U3RhdHVzSURUZXh0LEJpbGxpbmdDb3VudHJ5SUQsQmlsbGluZ0NvdW50cnlJRFRleHQsQmlsbGluZ1Byb3ZpbmNlSUQsQmlsbGluZ1Byb3ZpbmNlSURUZXh0LEJpbGxpbmdEaXN0cmljdElELEJpbGxpbmdEaXN0cmljdElEVGV4dCxCaWxsaW5nV2FyZElELEJpbGxpbmdXYXJkSURUZXh0LERlbGl2ZXJ5T3JkZXJOdW1iZXIsUGhvbmUsQWNjb3VudFRlbCxTaGlwcGluZ0FkZHJlc3MsRm9ybUxheW91dElELEZvcm1MYXlvdXRJRFRleHQsQWNjb3VudE93bmVySUQsSXNQYXJlbnRTYWxlT3JkZXIsT3Bwb3J0dW5pdHlJRCxPcHBvcnR1bml0eUlEVGV4dCxSb2xlT3duZXJJRCxJc1VzZUN1cnJlbmN5LEV4Y2hhbmdlUmF0ZSxQYXJlbnRJRCxQYXJlbnRJRFRleHQsUXVvdGVJRCxRdW90ZUlEVGV4dCxDb250YWN0SUQsQ29udGFjdElEVGV4dCxFYXJuaW5nUG9pbnQsRXhjaGFuZ2VQb2ludCxQYWlkRGF0ZSxEZWxpdmVyeURhdGUsQXBwcm92ZWRTdGF0dXNJRCxUYWdJRCxUYWdJRFRleHQsRXhwZWN0ZWREZWxpdmVyeURhdGUsRGVsaXZlcnlQYXJ0bmVySUQsRGVsaXZlcnlQYXJ0bmVyU3RhdHVzSUQsRGVsaXZlcnlQYXJ0bmVyU3RhdHVzSURUZXh0LEVjb21tZXJjZUlELFByb2R1Y3Rpb25Db25maXJtYXRpb25TdGF0dXNJRCxQcm9kdWN0aW9uQ29uZmlybWF0aW9uU3RhdHVzSURUZXh0LFByb2R1Y3Rpb25EYXRlLFNhbGVPcmRlclR5cGVJRA==",
    "CustomColumns": "Q3VzdG9tRmllbGQyMw==",
    "Sorts": [{"SortBy": "ModifiedDate", "Type": 0, "SortDirection": 1}],
    "Start": 0,
    "Page": 1,
    "PageSize": 20,
    "Filters": [],
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
    "SessionID": "55dc65e7-41ee-fcb6-fd21-7118cb82cb3c",
    "LayoutCodeCheckPermission": "SaleOrder",
    "AISearchKeyword": ""
}

def test_misa_api():
    print("\n" + "="*80)
    print("🔧 TEST MISA API - STANDALONE")
    print("="*80)
    
    # Yêu cầu user input
    print("\n📝 Nhập thông tin:")
    
    authorization = input("1️⃣  Authorization token (Bearer ...): ").strip()
    if not authorization:
        print("❌ Thiếu authorization!")
        return
    
    order_name = input("2️⃣  Sales order name (ví dụ: DH115524948215998): ").strip()
    if not order_name:
        print("❌ Thiếu order name!")
        return
    
    company_code = input("3️⃣  Company code (ví dụ: 3R2PY2F4): ").strip()
    if not company_code:
        company_code = "3R2PY2F4"
        print(f"   → Dùng mặc định: {company_code}")
    
    # Tạo headers
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "vi,en-US;q=0.9,en;q=0.8",
        "authorization": f"Bearer {authorization}" if not authorization.startswith("Bearer") else authorization,
        "companycode": company_code,
        "content-type": "application/json",
        "layoutcode": "saleorder",
        "x-misa-language": "vi-VN"
    }
    
    # Tạo payload
    payload = copy.deepcopy(PAYLOAD_TEMPLATE)
    payload['AISearchKeyword'] = order_name
    payload['PageSize'] = 1
    
    print("\n" + "-"*80)
    print("📤 Payload gửi đi:")
    print(f"  AISearchKeyword: {payload['AISearchKeyword']}")
    print(f"  Filters: {payload['Filters']}")
    print(f"  PageSize: {payload['PageSize']}")
    print(f"  SessionID: {payload['SessionID']}")
    
    print("\n📤 Headers:")
    for key, val in headers.items():
        if 'authorization' in key.lower():
            print(f"  {key}: Bearer {val[7:30]}...")
        else:
            print(f"  {key}: {val}")
    
    # Gọi API
    print("\n" + "-"*80)
    print(f"🔗 Gọi: POST {MISA_GRID_URL}")
    
    try:
        response = requests.post(
            MISA_GRID_URL,
            headers=headers,
            json=payload,
            timeout=30
        )
        
        print(f"✅ HTTP Status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ Error response:")
            print(f"   {response.text[:500]}")
            return
        
        data = response.json()
        
        print("\n" + "-"*80)
        print("📥 RESPONSE:")
        print(f"  Success: {data.get('Success')}")
        print(f"  Message: {data.get('Message', 'N/A')}")
        
        items = data.get('Data', [])
        print(f"  Items count: {len(items)}")
        
        if data.get('Success'):
            if items:
                print("\n" + "-"*80)
                print("📋 ITEMS CHI TIẾT (first 10):")
                for idx, item in enumerate(items[:10]):
                    print(f"\n  [{idx}] Item:")
                    print(f"      SaleOrderNo: {item.get('SaleOrderNo', 'N/A')}")
                    print(f"      SaleOrderName: {item.get('SaleOrderName', 'N/A')[:80]}")
                    print(f"      ShippingAddress: {item.get('ShippingAddress', 'N/A')[:100]}")
                    print(f"      AccountName: {item.get('AccountName', 'N/A')[:50]}")
                
                # 🔍 ANALYSIS
                print("\n" + "="*80)
                print("🔍 PHÂN TÍCH:")
                
                # Check if search keyword is in returned items
                searched_keyword = order_name
                found_match = False
                for idx, item in enumerate(items):
                    item_no = item.get('SaleOrderNo', '')
                    if item_no == searched_keyword:
                        print(f"✅ Tìm thấy match tại item [{idx}]:")
                        print(f"   SaleOrderNo: {item_no}")
                        print(f"   Address: {item.get('ShippingAddress', 'N/A')[:100]}")
                        found_match = True
                        break
                
                if not found_match:
                    print(f"❌ Không tìm thấy match cho '{searched_keyword}'!")
                    print(f"   Tìm được {len(items)} items nhưng không có order nào khớp")
                    print(f"\n   → AISearchKeyword BỊ IGNORED!")
                    print(f"   → API trả về 20 items đầu tiên, không filter")
                
                # Check if all items have same address
                addresses = [item.get('ShippingAddress', 'N/A') for item in items]
                unique_addresses = set(addresses)
                print(f"\n📊 Addresses statistics:")
                print(f"   Total items: {len(items)}")
                print(f"   Unique addresses: {len(unique_addresses)}")
                if len(unique_addresses) == 1:
                    print(f"   ⚠️  Tất cả items có cùng 1 address: {addresses[0][:80]}")
                else:
                    print(f"   ✅ Items có addresses khác nhau")
                
            else:
                print("❌ API trả về mảng Data trống!")
        else:
            print("\n❌ API lỗi!")
        
        # Save full response
        with open('misa_response.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("\n💾 Full response đã save vào: misa_response.json")
        
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Request error: {str(e)}")
    except json.JSONDecodeError as e:
        print(f"\n❌ JSON parse error: {str(e)}")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_misa_api()
    print("\n" + "="*80)
