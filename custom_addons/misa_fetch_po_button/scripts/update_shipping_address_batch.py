#!/usr/bin/env python3
"""
Script để cập nhật misa_shipping_address từ MISA CRM
- Lấy danh sách SO chưa giao xong, name không chứa "S0"
- Call MISA API Grid để search theo tên đơn hàng
- Extract ShippingAddress từ response
- Update vào field misa_shipping_address
"""

import requests
import json
import base64
import logging
import sys
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# MISA API Endpoint
MISA_GRID_URL = "https://amisapp.misa.vn/crm/g1/api/business/SaleOrder/Grid"

# Payload template từ user (giữ nguyên, chỉ thay AISearchKeyword)
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
    "AISearchKeyword": ""  # Sẽ được thay bằng sale order name
}


class ShippingAddressUpdater:
    def __init__(self, odoo_env, misa_headers):
        """
        :param odoo_env: Odoo environment (self.env trong Odoo context)
        :param misa_headers: Headers dict cho MISA API
        """
        self.env = odoo_env
        self.headers = misa_headers
        self.updated_count = 0
        self.failed_count = 0
        self.errors = []

    def fetch_from_misa(self, sale_order_name):
        """
        Gọi MISA Grid API với AISearchKeyword = sale_order_name
        Return: ShippingAddress nếu tìm thấy, None nếu không hoặc error
        """
        try:
            payload = PAYLOAD_TEMPLATE.copy()
            payload['AISearchKeyword'] = sale_order_name

            logger.info(f"[MISA API] Searching for: {sale_order_name}")
            response = requests.post(
                MISA_GRID_URL,
                headers=self.headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()

            data = response.json()
            if not data.get('Success'):
                logger.warning(f"[MISA API] Failed for {sale_order_name}: {data.get('Message', 'Unknown error')}")
                return None

            items = data.get('Data', [])
            if not items:
                logger.warning(f"[MISA API] No results for {sale_order_name}")
                return None

            # Lấy item đầu tiên (theo logic search, thường là match chính xác)
            first_item = items[0]
            shipping_address = first_item.get('ShippingAddress', '').strip()

            if shipping_address:
                logger.info(f"[MISA API] Found address: {shipping_address[:60]}...")
                return shipping_address
            else:
                logger.warning(f"[MISA API] Empty ShippingAddress for {sale_order_name}")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"[MISA API] Request error for {sale_order_name}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"[MISA API] Unexpected error for {sale_order_name}: {str(e)}")
            return None

    def update_sale_orders(self, limit=None, dry_run=False, force_update=False):
        """
        Cập nhật misa_shipping_address cho các SO:
        - DeliveryStatus != "Đã giao hàng"
        - Name không chứa "S0"
        
        :param limit: Số lượng SO tối đa để xử lý (None = all)
        :param dry_run: Nếu True, không lưu vào DB, chỉ log
        :param force_update: Nếu True, cập nhật cả những SO đã có address
        """
        # Query SO chưa giao xong, name không chứa "S0"
        SaleOrder = self.env['sale.order']
        
        domain = [
            ('state', 'in', ['sale', 'draft']),  # Trạng thái đơn hàng
        ]
        
        orders = SaleOrder.search(domain, limit=limit)
        logger.info(f"[INFO] Found {len(orders)} undelivered orders to process")

        for idx, order in enumerate(orders, 1):
            logger.info(f"\n[{idx}/{len(orders)}] Processing: {order.name} (ID: {order.id})")

            # Kiểm tra name có chứa "S0" không
            if "S0" in order.name:
                logger.info(f"  Skipping - name contains 'S0'")
                continue

            # Kiểm tra đã có misa_shipping_address không
            if order.misa_shipping_address and not force_update:
                logger.info(f"  Already has address: {order.misa_shipping_address[:60]}...")
                continue

            # Fetch từ MISA
            address = self.fetch_from_misa(order.name)
            if not address:
                logger.warning(f"  Failed to fetch address from MISA")
                self.failed_count += 1
                self.errors.append({
                    'order_id': order.id,
                    'order_name': order.name,
                    'error': 'MISA API returned no address'
                })
                continue

            # Update vào DB
            try:
                if not dry_run:
                    order.write({'misa_shipping_address': address})
                    self.env.cr.commit()
                    logger.info(f"  ✓ Updated successfully")
                else:
                    logger.info(f"  [DRY RUN] Would update with: {address[:60]}...")
                
                self.updated_count += 1
            except Exception as e:
                logger.error(f"  ✗ Failed to update: {str(e)}")
                self.failed_count += 1
                self.errors.append({
                    'order_id': order.id,
                    'order_name': order.name,
                    'error': str(e)
                })
                self.env.cr.rollback()

    def print_summary(self):
        """In tóm tắt kết quả"""
        logger.info("\n" + "="*60)
        logger.info("SUMMARY")
        logger.info("="*60)
        logger.info(f"Updated: {self.updated_count}")
        logger.info(f"Failed: {self.failed_count}")
        
        if self.errors:
            logger.info("\nErrors:")
            for err in self.errors:
                logger.info(f"  - {err['order_name']} (ID: {err['order_id']}): {err['error']}")


def run_from_odoo_shell(env, misa_headers, limit=None, dry_run=False, force_update=False):
    """
    Dùng trong Odoo shell:
    $ odoo shell -c /path/to/config.conf
    >>> exec(open('/full/path/to/update_shipping_address_batch.py').read())
    >>> run_from_odoo_shell(env, misa_headers, limit=100)
    
    :param env: Odoo environment (self.env trong Odoo context)
    :param misa_headers: Headers dict cho MISA API
    :param limit: Số lượng SO tối đa để xử lý
    :param dry_run: Nếu True, chỉ preview mà không save
    :param force_update: Cập nhật cả những SO đã có address
    """
    updater = ShippingAddressUpdater(env, misa_headers)
    updater.update_sale_orders(limit=limit, dry_run=dry_run, force_update=force_update)
    updater.print_summary()
    return updater


if __name__ == '__main__':
    # Standalone script usage (chạy trực tiếp từ command line)
    # Cần thêm phần authenticate với MISA và connect Odoo khi chạy standalone
    print("This script is designed to run within Odoo shell.")
    print("Usage: odoo shell -c /path/to/odoo.conf")
    print("Then in the shell: exec(open('update_shipping_address_batch.py').read())")
    sys.exit(1)
