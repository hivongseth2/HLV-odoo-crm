#!/usr/bin/env python3
"""
Script để cập nhật misa_shipping_address từ MISA CRM
- Lấy danh sách SO chưa giao xong, name không chứa "S0"
- Call MISA API Grid để search theo tên đơn hàng
- Extract ShippingAddress từ response
- Update vào field misa_shipping_address
- Hỗ trợ pagination để tránh fetch lại các orders đã xử lý
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

            logger.info(f"[MISA API] Tìm kiếm: {sale_order_name}")
            response = requests.post(
                MISA_GRID_URL,
                headers=self.headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()

            data = response.json()
            if not data.get('Success'):
                logger.warning(f"[MISA API] Lỗi với {sale_order_name}: {data.get('Message', 'Lỗi không xác định')}")
                return None

            items = data.get('Data', [])
            if not items:
                logger.warning(f"[MISA API] Không tìm thấy do liệu cho {sale_order_name}")
                return None

            # Lấy item đầu tiên (theo logic search, thường là match chính xác)
            first_item = items[0]
            shipping_address = first_item.get('ShippingAddress', '').strip()

            if shipping_address:
                logger.info(f"[MISA API] Tìm thấy địa chỉ: {shipping_address[:60]}...")
                return shipping_address
            else:
                logger.warning(f"[MISA API] Địa chỉ trống cho {sale_order_name}")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"[MISA API] Request error for {sale_order_name}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"[MISA API] Unexpected error for {sale_order_name}: {str(e)}")
            return None

    def count_eligible_orders(self, exclude_with_address=True):
        """
        Đếm số lượng SO đủ điều kiện:
        - state in [sale, draft]
        - delivery_status != full (chưa giao xong)
        - name không chứa "S0"
        
        :param exclude_with_address: Nếu True, loại bỏ những đã có address
        :return: Số lượng eligible orders
        """
        SaleOrder = self.env['sale.order']
        
        domain = [
            ('state', 'in', ['sale', 'draft']),
            ('delivery_status', '!=', 'full'),
        ]
        
        all_orders = SaleOrder.search(domain)
        
        eligible_count = 0
        for order in all_orders:
            # Loại bỏ orders có chứa "S0"
            if "S0" in order.name:
                continue
            
            # Loại bỏ orders đã có address (nếu exc
            if exclude_with_address and order.misa_shipping_address:
                continue
            
            eligible_count += 1
        
        return eligible_count

    def update_sale_orders(self, page=1, page_size=20, dry_run=False, force_update=False):
        """
        Cập nhật misa_shipping_address cho các SO (pagination):
        - state in [sale, draft]
        - delivery_status != full (chưa giao xong)
        - Name không chứa "S0"
        - Support pagination để tránh fetch lại những đã làm
        
        :param page: Trang hiện tại (mặc định 1)
        :param page_size: Số SO per trang (mặc định 20)
        :param dry_run: Nếu True, không lưu vào DB, chỉ log
        :param force_update: Nếu True, cập nhật cả những SO đã có address
        """
        SaleOrder = self.env['sale.order']
        
        domain = [
            ('delivery_status', '!=', 'full'),
        ]
        
        # Tìm tất cả SO
        all_orders = SaleOrder.search(domain, order='id ASC')
        
        # Filter: loại bỏ "S0", và loại bỏ đã có address (trừ khi force_update)
        eligible_orders = []
        for order in all_orders:
            if "S0" in order.name:
                continue
            if order.misa_shipping_address and not force_update:
                continue
            eligible_orders.append(order)
        
        total_eligible = len(eligible_orders)
        logger.info(f"\n[THỐNG KÊ] Tổng cộng {total_eligible} đơn hàng chưa giao, tên khác 'S0'")
        
        # Pagination
        offset = (page - 1) * page_size
        paginated_orders = eligible_orders[offset:offset + page_size]
        
        logger.info(f"[TRANG {page}] Xử lý {len(paginated_orders)} đơn hàng (từ {offset + 1} đến {offset + len(paginated_orders)})")
        logger.info(f"[TRANG {page}] Trang tiếp theo: page={page + 1}, page_size={page_size} (nếu còn dữ liệu)")
        
        if not paginated_orders:
            logger.warning(f"[TRANG {page}] Không có đơn hàng nào để xử lý!")
            return
        
        for idx, order in enumerate(paginated_orders, 1):
            logger.info(f"\n[{idx}/{len(paginated_orders)}] Xử lý: {order.name} (ID: {order.id})")

            # Fetch từ MISA
            address = self.fetch_from_misa(order.name)
            if not address:
                logger.warning(f"  ✗ Không thể fetch địa chỉ từ MISA")
                self.failed_count += 1
                self.errors.append({
                    'order_id': order.id,
                    'order_name': order.name,
                    'error': 'MISA API không trả về dữ liệu'
                })
                continue

            # Update vào DB
            try:
                if not dry_run:
                    order.write({'misa_shipping_address': address})
                    self.env.cr.commit()
                    logger.info(f"  ✓ Cập nhật thành công")
                else:
                    logger.info(f"  [CHẢ CHẠY] Sẽ cập nhật: {address[:60]}...")
                
                self.updated_count += 1
            except Exception as e:
                logger.error(f"  ✗ Lỗi khi cập nhật: {str(e)}")
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
        logger.info("THỐNG KÊ KẾT QUẢ")
        logger.info("="*60)
        logger.info(f"Cập nhật thành công: {self.updated_count}")
        logger.info(f"Lỗi: {self.failed_count}")
        
        if self.errors:
            logger.info("\nChi tiết lỗi:")
            for err in self.errors:
                logger.info(f"  - {err['order_name']} (ID: {err['order_id']}): {err['error']}")
        
        logger.info("="*60)


def run_from_odoo_shell(env, misa_headers, page=1, page_size=20, dry_run=False, force_update=False):
    """
    Dùng trong Odoo shell:
    $ odoo shell -c /path/to/config.conf
    >>> exec(open('/full/path/to/update_shipping_address_batch.py').read())
    
    # Lần 1: Xử lý 20 cái đầu
    >>> updater = run_from_odoo_shell(env, misa_headers, page=1, page_size=20)
    
    # Lần 2: Xử lý 20 cái tiếp theo
    >>> updater = run_from_odoo_shell(env, misa_headers, page=2, page_size=20)
    
    :param env: Odoo environment (self.env trong Odoo context)
    :param misa_headers: Headers dict cho MISA API
    :param page: Số trang (mặc định 1)
    :param page_size: Số SO per trang (mặc định 20)
    :param dry_run: Nếu True, chỉ preview mà không save
    :param force_update: Cập nhật cả những SO đã có address
    """
    updater = ShippingAddressUpdater(env, misa_headers)
    
    # Hiển thị thống kê trước
    total_eligible = updater.count_eligible_orders(exclude_with_address=not force_update)
    logger.info(f"\n[THỐNG KÊ TỔNG] Có {total_eligible} đơn hàng cần cập nhật đến địa chỉ")
    logger.info(f"[PAGINATION] page_size={page_size}, cần {(total_eligible + page_size - 1) // page_size} trang")
    
    updater.update_sale_orders(page=page, page_size=page_size, dry_run=dry_run, force_update=force_update)
    updater.print_summary()
    return updater


if __name__ == '__main__':
    # Standalone script usage (chạy trực tiếp từ command line)
    # Cần thêm phần authenticate với MISA và connect Odoo khi chạy standalone
    print("Script này được thiết kế để chạy trong Odoo shell.")
    print("Cách sử dụng: odoo shell -c /path/to/odoo.conf")
    print("Sau đó trong shell: exec(open('update_shipping_address_batch.py').read())")
    sys.exit(1)
