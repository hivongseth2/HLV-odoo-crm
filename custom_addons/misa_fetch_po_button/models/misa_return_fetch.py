from odoo import models, fields, _
import logging
from datetime import datetime, timedelta, timezone
import requests
import json
import base64
import time

_logger = logging.getLogger(__name__)

class MisaReturnFetch(models.TransientModel):
    _name = "misa.return.fetch"
    _description = "MISA Return Order Fetch"
    
    date_from = fields.Date(string="Từ ngày", required=True)
    date_to = fields.Date(string="Đến ngày", required=True)

    def _to_naive_utc(self, dt_str):
        """Chuyển đổi '2025-10-16T00:00:00.000+07:00' -> naive UTC datetime"""
        if not dt_str:
            return False
        try:
            aware = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            return aware.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception as e:
            _logger.warning("Không thể parse datetime '%s': %s", dt_str, e)
            return False

    def action_fetch_return_orders(self):
        """Hàm chính: Fetch đơn hàng trả về từ MISA và tạo phiếu nhập kho"""
        
        # Setup
        misa_utils = self.env['misa.api.utils']
        odoo_utils = self.env['odoo.utils']
        misa_config = self.env['misa.config']
        access_token = misa_utils._get_misa_token()
        headers = misa_config.get_default_headers(access_token)
        
        # Chuẩn bị thời gian
        date_from_utc = datetime.combine(self.date_from, datetime.min.time()) - timedelta(hours=7)
        date_to_utc = datetime.combine(self.date_to, datetime.max.time()) - timedelta(hours=7)
        
        # Mapping kho
        stock_mapping = {
            "HCM": "TSN/Stock",
            "BENCAM": "KBC/Tồn kho",
            "HIENDUC": "KHD/Tồn kho",
            "HCM_SHOWROOM": "TSNSR/Stock"
        }
        
        total_created = self._fetch_and_process_returns(
            misa_utils, headers, date_from_utc, date_to_utc, 
            odoo_utils, stock_mapping
        )
        
        # Thông báo kết quả
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Hoàn thành'),
                'message': _('Đã tạo %s phiếu nhập kho từ đơn hàng trả về') % total_created,
                'type': 'success',
                'sticky': False,
            }
        }

    def _fetch_and_process_returns(self, misa_utils, headers, date_from_utc, date_to_utc, 
                                    odoo_utils, stock_mapping):
        """Fetch paginated returns và xử lý từng đơn"""
        
        api_url = "https://actapp.misa.vn/g2/api/sa/v1/sa_return/paging_filter_v2"
        total_created = 0
        page_index = 1
        
        while True:
            payload = self._build_paging_payload(date_from_utc, date_to_utc, page_index)
            
            _logger.info("📄 Đang fetch trang %d...", page_index)
            response = misa_utils._fetch_with_retry(api_url, headers, payload)
            
            if response.status_code != 200:
                _logger.warning("❌ API thất bại trang %d", page_index)
                break
            
            page_data = response.json().get("Data", {}).get("PageData", [])
            if not page_data:
                _logger.info("✅ Hết dữ liệu trang %d", page_index)
                break
            
            # Xử lý từng đơn trả
            for return_order in page_data:
                try:
                    if self._process_return_order(return_order, headers, misa_utils, 
                                                 odoo_utils, stock_mapping):
                        total_created += 1
                except Exception as e:
                    refno = return_order.get("refno_finance", "UNKNOWN")
                    _logger.exception("❌ Lỗi xử lý đơn %s: %s", refno, e)
            
            page_index += 1
        
        return total_created

    def _build_paging_payload(self, date_from_utc, date_to_utc, page_index):
        """Xây dựng payload cho API paging_filter_v2"""
        return {
            "sort": '[{"property":3654,"desc":true,"data_type":3,"operand":1},'
                   '{"property":4018,"desc":true,"data_type":1,"operand":1}]',
            "filter": [
                {
                    "property": 3972,
                    "value": date_from_utc.isoformat() + "Z",
                    "operator": 10,
                    "operand": 1,
                    "data_type": 3
                },
                {
                    "property": 3972,
                    "value": date_to_utc.isoformat() + "Z",
                    "operator": 12,
                    "operand": 1,
                    "data_type": 3
                }
            ],
            "pageIndex": page_index,
            "pageSize": 20,
            "useSp": False,
            "view": 64,
            "summaryColumns": [5126, 5068, 5141, 5039],
            "loadMode": 2
        }

    def _process_return_order(self, return_order, headers, misa_utils, odoo_utils, stock_mapping):
        """Xử lý một đơn hàng trả về: validate → lấy detail → tạo picking + moves"""
        
        refno = return_order.get("refno_finance", "BTL-UNKNOWN")
        refid = return_order.get("refid")
        
        # Kiểm tra trùng
        if self.env["stock.picking"].search([("origin", "=", refno)], limit=1):
            _logger.info("⏭️ Bỏ qua %s (đã tồn tại)", refno)
            return False
        
        # Lấy detail
        detail_data = self._fetch_return_detail(refid, headers, misa_utils)
        if not detail_data:
            _logger.warning("❌ Không lấy được chi tiết %s", refno)
            return False
        
        # Validate kho
        stock_code = detail_data[0].get("stock_code", "").strip().replace(" ", "").upper()
        location = self._validate_and_get_location(stock_code, stock_mapping, refno)
        if not location:
            return False
        
        warehouse = self._get_warehouse_for_location(location, stock_code)
        if not warehouse:
            return False
        
        # Setup picking
        partner = odoo_utils._get_or_create_partner(return_order.get("account_object_name", ""))
        self._update_partner_info(partner, return_order)
        
        picking = self._create_picking(
            partner, warehouse, refno, location,
            return_order, detail_data
        )
        
        return True if picking else False

    def _validate_and_get_location(self, stock_code, stock_mapping, refno):
        """Validate stock code và lấy location
        
        Args:
            stock_code: Mã kho từ MISA (HCM, BENCAM, HIENDUC, HCM_SHOWROOM)
            stock_mapping: Dict mapping stock_code → Odoo location path
            refno: Mã phiếu (để log)
            
        Returns:
            stock.location record or None
        """
        
        if stock_code not in stock_mapping:
            _logger.error("❌ %s: stock_code '%s' không hỗ trợ", refno, stock_code)
            return None
        
        location_path = stock_mapping[stock_code]
        location = self.env["stock.location"].search(
            [("complete_name", "=", location_path)], limit=1
        )
        
        if not location:
            _logger.error("❌ %s: Không tìm location '%s'", refno, location_path)
            return None
        
        _logger.info("✅ %s: Location '%s' (%s)", refno, location_path, location.id)
        return location

    def _get_warehouse_for_location(self, location, stock_code):
        """Lấy warehouse từ location
        
        Args:
            location: stock.location record
            stock_code: Mã kho (để log)
            
        Returns:
            stock.warehouse record or None
        """
        
        # location.warehouse_id có thể null, cần trace về kho
        warehouse = self.env["stock.warehouse"].search(
            [("view_location_id", "=", location.parent_path.split("/")[-2] if "/" in location.parent_path else location.parent_path)],
            limit=1
        )
        
        # Fallback: lấy warehouse đầu tiên (thường là mặc định)
        if not warehouse:
            warehouse = self.env["stock.warehouse"].search([], limit=1)
        
        if not warehouse:
            _logger.error("❌ Không tìm warehouse cho %s", stock_code)
            return None
        
        _logger.info("✅ Warehouse: %s", warehouse.name)
        return warehouse

    def _update_partner_info(self, partner, return_order):
        """Update thông tin khách hàng từ dữ liệu MISA
        
        Args:
            partner: res.partner record
            return_order: Dict từ MISA API
        """
        
        update_vals = {}
        
        if return_order.get("account_object_address"):
            update_vals['street'] = return_order.get("account_object_address", "")
        
        if return_order.get("tel"):
            update_vals['phone'] = return_order.get("tel", "")
        
        if update_vals:
            partner.write(update_vals)
            _logger.info("✅ Updated partner: %s", partner.name)

    def _create_picking(self, partner, warehouse, refno, location, return_order, detail_data):
        """Tạo picking + moves + collect order_codes
        
        Cấu trúc:
        - Picking name: Tự động sinh (Odoo)
        - Origin: Mã đơn gốc (đơn hàng đầu tiên) - đưa lên chứng từ gốc
        - Note: Lý do trả hàng + danh sách order_codes
        """
        
        refdate_str = return_order.get("refdate") or return_order.get("posted_date")
        scheduled_date = self._to_naive_utc(refdate_str) or fields.Datetime.now()
        journal_memo = return_order.get("journal_memo", "")
        
        # Tạo moves trước để collect order_codes
        picking_tmp = self.env["stock.picking"].new({
            "picking_type_id": warehouse.in_type_id.id,
        })
        
        order_codes = []
        for line in detail_data:
            order_code = line.get("order_code", "").strip()
            if order_code and order_code not in order_codes:
                order_codes.append(order_code)
        
        # Lấy order_code đầu tiên làm origin (chứng từ gốc)
        origin_code = order_codes[0] if order_codes else refno
        
        # Tạo picking
        picking_vals = {
            "name": refno,  # ← Tên phiếu = mã phiếu trả từ MISA (BTL00992)
            "partner_id": partner.id,
            "picking_type_id": warehouse.in_type_id.id,
            "location_id": self.env.ref('stock.stock_location_customers').id,
            "location_dest_id": location.id,
            "origin": origin_code,  # ← Mã đơn gốc (chứng từ gốc)
            "scheduled_date": scheduled_date,
            "move_type": "direct",
        }
        
        # Build note: chỉ lý do trả hàng
        if journal_memo:
            picking_vals['note'] = journal_memo
        
        picking = self.env["stock.picking"].create(picking_vals)
        
        # Tạo moves
        for line in detail_data:
            self._create_stock_move(picking, line, location, self.env['odoo.utils'])
        
        # Confirm
        if not picking.move_ids_without_package:
            picking.unlink()
            _logger.warning("⚠️ Không có move hợp lệ, xóa %s", refno)
            return None
        
        picking.action_confirm()
        _logger.info("✅ Phiếu %s | origin=%s | refno=%s | order_codes=%s", 
                    picking.name, origin_code, refno, ", ".join(order_codes) or "N/A")
        
        return picking

    def _fetch_return_detail(self, refid, headers, misa_utils):
        """Fetch chi tiết đơn trả từ API detail_full (với optimized payload + headers)
        
        ⚠️ QUAN TRỌNG:
        - Dùng detail_full để lấy order_code chính xác từng sản phẩm
        - Payload minimal: chỉ sa_return_detail, bỏ Links
        - Headers đầy đủ: Cookie, X-MISA-Context, X-Device
        - Response: ~0.5-5s (không timeout)
        """
        
        req_payload = [{
            "Type": "sa_return",
            "Key": refid,
            "RefType": 3040,
            "RefTypeCategory": 354,
            "Details": [{"Type": "sa_return_detail", "Alias": "detail", "View": "view_sa_return_detail"}],
            "Links": []
        }]
        
        req_base64 = base64.b64encode(
            json.dumps(req_payload, separators=(',', ':')).encode('utf-8')
        ).decode('utf-8')
        
        detail_url = f"https://actapp.misa.vn/g2/api/sa/v1/sa_return/detail_full?req={req_base64}"
        
        try:
            _logger.info("🔄 detail_full cho %s...", refid)
            
            start_time = time.time()
            response = requests.get(detail_url, headers=headers, timeout=90)
            elapsed = time.time() - start_time
            
            _logger.info("⏱️ Response: %.2f giây | HTTP %s", elapsed, response.status_code)
            
            if response.status_code != 200:
                _logger.error("❌ HTTP %s", response.status_code)
                return None
            
            result = response.json()
            if not result.get("Success"):
                _logger.error("❌ Success=False")
                return None
            
            detail_data = result.get("Data", {}).get("sa_return_detail", [])
            if not detail_data:
                _logger.warning("⚠️ Không có sa_return_detail")
                return None
            
            _logger.info("✅ Lấy %d dòng chi tiết", len(detail_data))
            return detail_data
                
        except requests.exceptions.Timeout:
            _logger.error("❌ Timeout (>90s)")
            return None
        except Exception as e:
            _logger.exception("❌ Error: %s", e)
            return None

    def _create_stock_move(self, picking, line, location, odoo_utils):
        """Tạo stock move từ dòng chi tiết (order_code đã lưu ở picking.note)"""
        
        product_code = line.get("inventory_item_code", "").strip()
        product_name = line.get("description", "").strip()
        qty = float(line.get("quantity", 0))
        unit_name = line.get("unit_name", "Cái").strip()
        price = float(line.get("unit_price", 0))
        order_code = line.get("order_code", "").strip()
        
        # Log
        if order_code:
            _logger.info("📦 order_code=%s | product=%s | qty=%s", order_code, product_code, qty)
        else:
            _logger.warning("⚠️ Thiếu order_code | product=%s | qty=%s", product_code, qty)
        
        # Validate
        if not product_code or qty <= 0:
            _logger.warning("⏭️ Skip invalid: %s (qty=%s)", product_code, qty)
            return
        
        # Get/create product
        product = odoo_utils._get_or_create_product(
            code=product_code,
            name=product_name,
            unit_name=unit_name,
            cost=price,
            purchase_ok=True,
            sale_ok=True
        )
        
        if not product:
            _logger.warning("❌ Không tạo được product %s", product_code)
            return
        
        # Create move
        move_vals = {
            "name": product_name or product_code,
            "product_id": product.id,
            "product_uom_qty": qty,
            "product_uom": product.uom_id.id,
            "picking_id": picking.id,
            "location_id": picking.location_id.id,
            "location_dest_id": location.id,
            "state": "draft",  # ← Đặt state để tránh error weight computation
        }
        
        self.env["stock.move"].create(move_vals)
        _logger.info("✅ Move created: %s (qty=%s)", product_code, qty)
