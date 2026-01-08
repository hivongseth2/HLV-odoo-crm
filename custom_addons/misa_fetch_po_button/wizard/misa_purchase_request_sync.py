# -*- coding: utf-8 -*-
"""
Wizard đồng bộ Yêu cầu mua hàng (Purchase Request) từ MISA CRM về Odoo
Chỉ chọn theo ngày, không có field mã yêu cầu (mã yêu cầu được xử lý qua API riêng)
"""
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
from dateutil.parser import parse
import logging

_logger = logging.getLogger(__name__)


class MisaPurchaseRequestSyncWizard(models.TransientModel):
    _name = 'misa.purchase.request.sync.wizard'
    _description = 'Đồng bộ Yêu cầu mua hàng từ MISA'

    from_date = fields.Date(
        string="Từ ngày",
        required=True,
        default=lambda self: fields.Date.today() - timedelta(days=7)
    )
    to_date = fields.Date(
        string="Đến ngày",
        required=True,
        default=fields.Date.today
    )
    log_text = fields.Text(string='Kết quả', readonly=True)
    state = fields.Selection([
        ('draft', 'Chuẩn bị'),
        ('done', 'Hoàn thành')
    ], default='draft')

    def _get_purchase_request_payload(self, page):
        """Tạo payload cho API PurchaseRequest/Grid
        
        Note: API Purchase Request không hỗ trợ date filter như Sale Order,
        nên dùng empty filters và filter client-side sau khi fetch.
        """
        page_size = 20
        start = (page - 1) * page_size if page > 0 else 0

        return {
            # Columns từ working payload của user
            "Columns": "SUQsUHVyY2hhc2VSZXF1ZXN0Tm8sUmVxdWVzdERhdGUsT3duZXJJRCxPd25lcklEVGV4dCxQcm9jZXNzU3RhdHVzSUQsUHJvY2Vzc1N0YXR1c0lEVGV4dCxQdXJjaGFzZVN0YXR1c0lELFB1cmNoYXNlU3RhdHVzSURUZXh0LExpc3RQcm9kdWN0SUQsTGlzdFByb2R1Y3RJRFRleHQsRm9ybUxheW91dElELEZvcm1MYXlvdXRJRFRleHQsUHJvY2Vzc0lELFVSTFZpZXdQcm9jZXNz",
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
            # Empty filters - filter client-side
            "Filters": [],
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
            "SessionID": "67667793-1891-4493-820f-51ea32ebe990",
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

    def action_sync(self):
        """Thực hiện đồng bộ Purchase Request từ MISA theo khoảng ngày"""
        self.ensure_one()
        
        logs = []
        logs.append("=" * 50)
        logs.append("ĐỒNG BỘ YÊU CẦU MUA HÀNG TỪ MISA CRM")
        logs.append("=" * 50)
        
        try:
            misa_utils = self.env['misa.api.utils']
            misa_config = self.env['misa.config']
            
            # Lấy CRM token
            logs.append("\n📥 Đang đăng nhập MISA CRM...")
            crm_token = misa_utils._fetch_login_crm_token()
            logs.append("✅ Đăng nhập thành công")
            
            # Build headers
            headers = misa_config.get_crm_header(crm_token)
            
            # Build datetime range - dùng múi giờ Việt Nam
            start_datetime = datetime.combine(self.from_date, datetime.min.time())
            end_datetime = datetime.combine(self.to_date, datetime.max.time())
            
            # Log chi tiết khoảng thời gian filter
            iso_start = start_datetime.strftime("%Y-%m-%dT%H:%M:%S.000+07:00")
            iso_end = end_datetime.strftime("%Y-%m-%dT%H:%M:%S.000+07:00")
            
            logs.append(f"\n📆 Khoảng thời gian: {self.from_date} đến {self.to_date}")
            logs.append(f"🕐 Filter API: {iso_start} → {iso_end}")

            
            # API URL
            api_url = "https://amisapp.misa.vn/crm/g1/api/business/PurchaseRequest/Grid"
            
            # Thống kê
            total_fetched = 0
            created_count = 0
            updated_count = 0
            skipped_count = 0
            
            page = 1
            PurchaseRequest = self.env['purchase.request'].sudo()
            PurchaseRequestLine = self.env['purchase.request.line'].sudo()
            
            while True:
                # Payload không có date filter - sẽ filter client-side
                payload = self._get_purchase_request_payload(page)
                
                # Log payload để debug
                _logger.info("📤 Request payload: %s", payload)
                
                try:
                    response = requests.post(api_url, headers=headers, json=payload, timeout=60)
                    
                    # Log response status
                    logs.append(f"\n📡 API Response Status: {response.status_code}")
                    _logger.info("📡 API Response Status: %s", response.status_code)
                    
                    response.raise_for_status()
                    data = response.json()
                    
                    # Log response details
                    total = data.get("Total", 0)
                    page_count_api = data.get("PageCount", 0)
                    code = data.get("Code", "N/A")
                    success = data.get("Success", "N/A")
                    
                    logs.append(f"📊 Response - Code: {code}, Success: {success}, Total: {total}, PageCount: {page_count_api}")
                    _logger.info("📊 Response: Code=%s Success=%s Total=%s PageCount=%s", code, success, total, page_count_api)
                    
                    # Log raw response nếu không có data
                    if not data.get("Data"):
                        logs.append(f"⚠️ Raw response keys: {list(data.keys())}")
                        _logger.warning("⚠️ No Data in response. Keys: %s", list(data.keys()))
                    
                except Exception as e:
                    logs.append(f"❌ Lỗi khi gọi API: {e}")
                    _logger.exception("❌ API Error: %s", e)
                    break
                
                requests_data = data.get("Data", [])
                if not requests_data:
                    if page == 1:
                        logs.append("\n⚠️ Không có dữ liệu từ API")
                    break

                
                logs.append(f"\n📄 Trang {page}: {len(requests_data)} yêu cầu từ API")
                
                # Filter client-side theo khoảng ngày
                filtered_count = 0
                for pr_data in requests_data:
                    pr_no = pr_data.get("PurchaseRequestNo") or ""
                    request_date_str = pr_data.get("RequestDate")
                    owner_text = pr_data.get("OwnerIDText") or ""
                    product_codes = pr_data.get("ListProductIDText") or ""
                    
                    if not pr_no:
                        skipped_count += 1
                        continue
                    
                    # Parse ngày
                    request_date = None
                    if request_date_str:
                        try:
                            request_date = parse(request_date_str).date()
                        except Exception:
                            request_date = None
                    
                    # Client-side date filter
                    if request_date:
                        if request_date < self.from_date or request_date > self.to_date:
                            _logger.debug("Skipped %s: date %s not in range", pr_no, request_date)
                            continue
                    
                    filtered_count += 1
                    total_fetched += 1

                    
                    # Tìm existing
                    existing_pr = PurchaseRequest.search([('name', '=', pr_no)], limit=1)
                    
                    if existing_pr:
                        # Cập nhật nếu đã tồn tại
                        vals = {
                            'misa_requester_text': owner_text,
                        }
                        if request_date:
                            vals['date_start'] = request_date
                        
                        existing_pr.write(vals)
                        updated_count += 1
                        logs.append(f"   🔄 Cập nhật: {pr_no}")
                    else:
                        # Tạo mới với trạng thái to_approve
                        vals = {
                            'name': pr_no,
                            'date_start': request_date or fields.Date.today(),
                            'misa_requester_text': owner_text,
                            'state': 'to_approve',
                        }
                        
                        new_pr = PurchaseRequest.create(vals)
                        
                        # Tạo các dòng sản phẩm
                        product_lines = self._find_or_create_products_from_codes(product_codes)
                        for pline in product_lines:
                            PurchaseRequestLine.create({
                                'request_id': new_pr.id,
                                'product_id': pline['product_id'],
                                'name': pline['name'],
                                'product_qty': pline['product_qty'],
                                'product_uom_id': pline['product_uom_id'],
                            })
                        
                        created_count += 1
                        logs.append(f"   ✅ Tạo mới: {pr_no} ({len(product_lines)} sản phẩm)")
                
                # Log số lượng đã filter
                if filtered_count > 0:
                    logs.append(f"   📋 Lọc được {filtered_count} yêu cầu trong khoảng ngày")
                
                # Kiểm tra phân trang
                page_count = data.get("PageCount", 1)
                if page >= page_count:
                    break
                page += 1
            
            # Tổng kết
            logs.append("\n" + "=" * 50)
            logs.append("HOÀN THÀNH!")
            logs.append("=" * 50)
            logs.append(f"📊 Tổng số từ MISA: {total_fetched}")
            logs.append(f"✅ Tạo mới: {created_count}")
            logs.append(f"🔄 Cập nhật: {updated_count}")
            logs.append(f"⏭️ Bỏ qua: {skipped_count}")
            
        except Exception as e:
            _logger.exception("Lỗi đồng bộ Purchase Request từ MISA")
            logs.append(f"\n❌ LỖI: {str(e)}")
        
        self.write({
            'log_text': '\n'.join(logs),
            'state': 'done'
        })
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_reset(self):
        """Reset wizard để chạy lại"""
        self.write({'state': 'draft', 'log_text': ''})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
