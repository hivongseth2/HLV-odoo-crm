# -*- coding: utf-8 -*-
"""
Wizard đồng bộ Đề nghị trả hàng bán từ MISA CRM
"""
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
from dateutil.parser import parse
import logging

_logger = logging.getLogger(__name__)


class MisaReturnSaleSyncWizard(models.TransientModel):
    _name = "misa.return.sale.sync.wizard"
    _description = "Đồng bộ đề nghị trả hàng từ MISA"

    from_date = fields.Date(
        string="Từ ngày",
        required=True,
        default=lambda self: fields.Date.today() - timedelta(days=7),
    )
    to_date = fields.Date(
        string="Đến ngày",
        required=True,
        default=fields.Date.today,
    )
    log_text = fields.Text(string="Kết quả", readonly=True)
    state = fields.Selection(
        [("draft", "Chuẩn bị"), ("done", "Hoàn thành")],
        default="draft",
    )

    def _get_grid_payload(self, page):
        """Tạo payload cho API ReturnSale/Grid"""
        page_size = 20
        start = (page - 1) * page_size if page > 0 else 0

        return {
            "Columns": "SUQsUmV0dXJuU2FsZU5vLFJldHVyblNhbGVOYW1lLFJldHVyblNhbGVEYXRlLEFjY291bnRJRCxBY2NvdW50SURUZXh0LFNhbGVPcmRlcklELFNhbGVPcmRlcklEVGV4dCxUb3RhbFN1bW1hcnksU3VnZ2VzdFN0YXR1c0lELFN1Z2dlc3RTdGF0dXNJRFRleHQsQmlsbGluZ0FkZHJlc3MsRm9ybUxheW91dElELEZvcm1MYXlvdXRJRFRleHQsT3duZXJJRCxPd25lcklEVGV4dCxJc1VzZUN1cnJlbmN5LEV4Y2hhbmdlUmF0ZSxDb250YWN0SUQsQ29udGFjdElEVGV4dA==",
            "Sorts": [{"SortBy": "ModifiedDate", "Type": 0, "SortDirection": 1}],
            "Start": start,
            "Page": page,
            "PageSize": page_size,
            "Filters": [],
            "Formula": "",
            "LayoutCode": "ReturnSale",
            "DefaultTotal": True,
            "IsMappingData": False,
            "MappingValueObject": {},
            # IsApproved removed
            "CustomPagingData": {},
            "IsUsedELTS": True,
            "ListGmailPage": [],
            "ListFacebookPage": {},
            "IsListPaging": True,
            "IsGetCache": True,
            "IsCheckInactive": False,
            "IsConverted": False,
            "SessionID": "return-sale-sync-wizard",
            "AISearchKeyword": "",
        }

    def action_sync(self):
        """Thực hiện đồng bộ Return Sale từ MISA theo khoảng ngày"""
        self.ensure_one()

        logs = []
        logs.append("=" * 50)
        logs.append("ĐỒNG BỘ ĐỀ NGHỊ TRẢ HÀNG BÁN TỪ MISA CRM")
        logs.append("=" * 50)

        try:
            misa_utils = self.env["misa.api.utils"]
            misa_config = self.env["misa.config"]

            # Lấy CRM token
            logs.append("\n📥 Đang đăng nhập MISA CRM...")
            crm_token = misa_utils._fetch_login_crm_token()
            logs.append("✅ Đăng nhập thành công")

            # Build headers
            headers = misa_config.get_crm_header(crm_token)

            # Log khoảng thời gian
            logs.append(f"\n📆 Khoảng thời gian: {self.from_date} đến {self.to_date}")

            # API URL - Use g1 instead of g2
            api_url = "https://amisapp.misa.vn/crm/g1/api/business/ReturnSale/Grid"

            # Thống kê
            total_fetched = 0
            created_count = 0
            updated_count = 0
            skipped_count = 0

            page = 1
            ReturnSaleRequest = self.env["return.sale.request"].sudo()

            while True:
                payload = self._get_grid_payload(page)
                
                # Log payload để debug
                _logger.info("📤 Request Payload Page %s: %s", page, payload)
                logs.append(f"\n📤 Đang gọi API trang {page}...")

                try:
                    response = requests.post(
                        api_url, headers=headers, json=payload, timeout=60
                    )
                    logs.append(f"📡 API Response Status: {response.status_code}")
                    
                    if response.status_code != 200:
                        logs.append(f"❌ API trả về lỗi: {response.text}")
                        _logger.error("API Error: %s", response.text)
                        break

                    data = response.json()
                    total = data.get("Total", 0)
                    page_count_api = data.get("PageCount", 0)
                    success = data.get("Success")
                    logs.append(f"📊 Success: {success}, Total: {total}, PageCount: {page_count_api}")
                    
                    if not success:
                         logs.append(f"⚠️ API báo Success=False. Data: {data}")

                except Exception as e:
                    logs.append(f"❌ Exception khi gọi API: {e}")
                    _logger.exception("API Exception: %s", e)
                    break

                requests_data = data.get("Data", [])
                if not requests_data:
                    if page == 1:
                        logs.append("\n⚠️ Không có dữ liệu từ API")
                    break

                logs.append(f"\n📄 Trang {page}: {len(requests_data)} đề nghị từ API")

                # Filter và xử lý từng record
                filtered_count = 0
                for rs_data in requests_data:
                    return_sale_no = rs_data.get("ReturnSaleNo") or ""
                    misa_id = rs_data.get("ID")
                    date_str = rs_data.get("ReturnSaleDate")
                    account_text = rs_data.get("AccountIDText") or ""
                    sale_order_text = rs_data.get("SaleOrderIDText") or ""
                    total_amount = rs_data.get("TotalSummary") or 0
                    owner_text = rs_data.get("OwnerIDText") or ""
                    billing_address = rs_data.get("BillingAddress") or ""

                    if not return_sale_no:
                        skipped_count += 1
                        continue

                    # Parse ngày
                    request_date = None
                    if date_str:
                        try:
                            request_date = parse(date_str).date()
                        except Exception:
                            request_date = None

                    # Client-side date filter
                    if request_date:
                        if request_date < self.from_date or request_date > self.to_date:
                            continue

                    filtered_count += 1
                    total_fetched += 1

                    # Fetch detail để lấy thêm thông tin
                    detail_data = self._fetch_detail(misa_id, headers)

                    # Parse detail
                    return_reason = ""
                    handling_method = ""
                    product_codes_text = ""
                    if detail_data:
                        return_reason = detail_data.get("CustomField13") or ""
                        handling_method = detail_data.get("CustomField14") or ""
                        product_codes_text = detail_data.get("ListProductIDText") or ""
                        billing_address = (
                            detail_data.get("BillingAddress") or billing_address
                        )

                    # Find or create partner
                    partner = False
                    if account_text:
                        odoo_utils = self.env["odoo.utils"].sudo()
                        partner = odoo_utils._get_or_create_partner(account_text)

                    # Find Sale Order
                    sale_order = False
                    if sale_order_text:
                        sale_order = self.env["sale.order"].sudo().search(
                            [("name", "=", sale_order_text)], limit=1
                        )

                    # Check existing
                    existing = ReturnSaleRequest.search(
                        [("misa_return_sale_no", "=", return_sale_no)], limit=1
                    )

                    vals = {
                        "misa_id": misa_id,
                        "misa_return_sale_no": return_sale_no,
                        "date": request_date or fields.Date.today(),
                        "partner_id": partner.id if partner else False,
                        "sale_order_id": sale_order.id if sale_order else False,
                        "total_amount": total_amount,
                        "return_reason": return_reason,
                        "handling_method": handling_method,
                        "delivery_address": billing_address,
                        "misa_owner_text": owner_text,
                    }

                    if existing:
                        existing.write(vals)
                        if product_codes_text:
                            existing._sync_lines_from_misa(product_codes_text)
                        updated_count += 1
                        logs.append(f"   🔄 Cập nhật: {return_sale_no}")
                    else:
                        vals["state"] = "to_approve"
                        new_record = ReturnSaleRequest.create(vals)
                        if product_codes_text:
                            new_record._sync_lines_from_misa(product_codes_text)
                        created_count += 1
                        logs.append(f"   ✅ Tạo mới: {return_sale_no}")

                if filtered_count > 0:
                    logs.append(
                        f"   📋 Lọc được {filtered_count} đề nghị trong khoảng ngày"
                    )

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
            _logger.exception("Lỗi đồng bộ Return Sale từ MISA")
            logs.append(f"\n❌ LỖI: {str(e)}")

        self.write({"log_text": "\n".join(logs), "state": "done"})

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _fetch_detail(self, misa_id, headers):
        """Fetch chi tiết đề nghị trả hàng từ FormDataNew API"""
        try:
            detail_url = f"https://amisapp.misa.vn/crm/g2/api/business/ReturnSale/FormDataNew/ReturnSale/122/{misa_id}"
            response = requests.get(detail_url, headers=headers, timeout=60)

            if response.status_code != 200:
                _logger.warning("Detail API failed for ID %s: %s", misa_id, response.status_code)
                return None

            result = response.json()
            if not result.get("Success"):
                return None

            return result.get("Data", {}).get("CurrentData", {})

        except Exception as e:
            _logger.warning("Error fetching detail for ID %s: %s", misa_id, e)
            return None

    def action_reset(self):
        """Reset wizard để chạy lại"""
        self.write({"state": "draft", "log_text": ""})
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
