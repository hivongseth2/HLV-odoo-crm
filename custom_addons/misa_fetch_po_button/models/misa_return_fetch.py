from odoo import models, fields, _
import logging
from datetime import datetime, timedelta, timezone
import requests

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
        """Hàm chính để fetch đơn hàng trả về từ MISA và tạo phiếu nhập kho"""
        
        # Khởi tạo các utils
        misa_utils = self.env['misa.api.utils']
        odoo_utils = self.env['odoo.utils']
        misa_config = self.env['misa.config']
        
        # Lấy token
        access_token = misa_utils._get_misa_token()
        headers = misa_config.get_default_headers(access_token)
        
        # Chuyển đổi ngày sang UTC
        date_from_utc = datetime.combine(self.date_from, datetime.min.time()) - timedelta(hours=7)
        date_to_utc = datetime.combine(self.date_to, datetime.max.time()) - timedelta(hours=7)
        
        # Payload cho API paging_filter_v2
        payload = {
            "sort": '[{"property":3654,"desc":true,"data_type":3,"operand":1},{"property":4018,"desc":true,"data_type":1,"operand":1}]',
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
            "pageIndex": 1,
            "pageSize": 20,
            "useSp": False,
            "view": 64,
            "summaryColumns": [5126, 5068, 5141, 5039],
            "loadMode": 2
        }
        
        # Mapping kho
        stock_mapping = {
            "HCM": "TSN/Stock",
            "BENCAM": "KBC/Tồn kho",
            "HIENDUC": "KHD/Tồn kho",
            "HCM_SHOWROOM": "TSNSR/Stock"
        }
        
        page_index = 1
        total_created = 0
        
        while True:
            payload["pageIndex"] = page_index
            _logger.info("📄 Đang fetch trang %s đơn hàng trả về...", page_index)
            
            # Gọi API lấy danh sách đơn trả về
            response = misa_utils._fetch_with_retry(
                "https://actapp.misa.vn/g2/api/sa/v1/sa_return/paging_filter_v2",
                headers, payload
            )
            
            if response.status_code != 200:
                _logger.warning("❌ Gọi API thất bại ở trang %s", page_index)
                break
            
            page_data = response.json().get("Data", {}).get("PageData", [])
            if not page_data:
                _logger.info("✅ Hết dữ liệu, dừng ở trang %s", page_index)
                break
            
            # Xử lý từng đơn hàng trả về
            for return_order in page_data:
                try:
                    if self._process_return_order(return_order, headers, misa_utils, odoo_utils, stock_mapping):
                        total_created += 1
                except Exception as e:
                    _logger.exception("❌ Lỗi khi xử lý đơn trả về %s: %s", 
                                    return_order.get("refno_finance"), e)
                    continue
            
            page_index += 1
        
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

    def _process_return_order(self, return_order, headers, misa_utils, odoo_utils, stock_mapping):
        """Xử lý một đơn hàng trả về"""
        
        refid = return_order.get("refid")
        refno = return_order.get("refno_finance", "BTL-UNKNOWN")
        journal_memo = return_order.get("journal_memo", "")
        supplier_name = return_order.get("account_object_name", "Unknown Customer")
        
        # Kiểm tra xem đã tạo phiếu nhập kho chưa
        existing_picking = self.env["stock.picking"].search([
            ("origin", "=", refno)
        ], limit=1)
        
        if existing_picking:
            _logger.info("⏭️  Bỏ qua đơn trả %s vì đã tồn tại phiếu nhập kho", refno)
            return False
        
        # Lấy chi tiết đơn hàng trả về
        detail_data = self._fetch_return_detail(refid, headers, misa_utils)
        if not detail_data:
            _logger.warning("❌ Không lấy được chi tiết đơn trả %s", refno)
            return False
        
        # detail_data bây giờ là PageData - một list các dòng sản phẩm
        if not detail_data or not isinstance(detail_data, list):
            _logger.warning("❌ Đơn trả %s không có chi tiết sản phẩm", refno)
            return False
        
        # Lấy mã kho từ dòng đầu tiên
        stock_code = detail_data[0].get("stock_code", "").strip().replace(" ", "").upper()
        
        # Kiểm tra kho
        if stock_code not in stock_mapping:
            _logger.warning("📛 Kho %s không nằm trong mapping, bỏ đơn trả %s", stock_code, refno)
            return False
        
        location_name = stock_mapping[stock_code]
        location = self.env['stock.location'].search([
            ('complete_name', '=', location_name)
        ], limit=1)
        
        if not location:
            _logger.warning("❌ Không tìm thấy stock.location cho kho %s (%s)", stock_code, location_name)
            return False
        
        # Tìm warehouse
        warehouse = self.env['stock.warehouse'].search([
            ('view_location_id', '=', location.location_id.id)
        ], limit=1)
        
        if not warehouse:
            _logger.warning("❌ Không tìm thấy warehouse cho kho %s", stock_code)
            return False
        
        picking_type = warehouse.in_type_id
        
        # Tạo/cập nhật partner
        partner = odoo_utils._get_or_create_partner(supplier_name)
        
        # Cập nhật thông tin đối tác
        partner_update_vals = {}
        account_object_code = return_order.get("account_object_code", "")
        account_object_address = return_order.get("account_object_address", "")
        
        if account_object_code and not partner.ref:
            partner_update_vals['ref'] = account_object_code
        if account_object_address and not partner.street:
            partner_update_vals['street'] = account_object_address
        
        if partner_update_vals:
            partner.write(partner_update_vals)
        
        # Lấy ngày trả hàng
        refdate_str = return_order.get("refdate") or return_order.get("posted_date")
        scheduled_date = self._to_naive_utc(refdate_str) or fields.Datetime.now()
        
        # Tạo phiếu nhập kho
        picking_vals = {
            "partner_id": partner.id,
            "picking_type_id": picking_type.id,
            "location_id": self.env.ref('stock.stock_location_customers').id,  # Từ khách hàng
            "location_dest_id": location.id,  # Đến kho
            "origin": refno,  # Mã đơn trả hàng
            "scheduled_date": scheduled_date,
            "move_type": "direct",
        }
        
        # Thêm ghi chú với journal_memo
        note_parts = []
        if journal_memo:
            note_parts.append(f"Lý do trả: {journal_memo}")
        
        if note_parts:
            picking_vals['note'] = " | ".join(note_parts)
        
        picking = self.env["stock.picking"].create(picking_vals)
        
        # Lưu order_code từng dòng vào picking note để track
        # (Mỗi sản phẩm có thể từ đơn gốc khác nhau)
        order_codes_in_detail = []
        
        # Tạo các dòng move từ detail_data (sa_return_detail từ detail_full API)
        # Mỗi line có order_code riêng
        for line in detail_data:
            order_code = line.get("order_code", "").strip()
            if order_code and order_code not in order_codes_in_detail:
                order_codes_in_detail.append(order_code)
            self._create_stock_move(picking, line, location, odoo_utils)
        
        # Xác nhận phiếu nhập kho
        if picking.move_ids_without_package:
            # Cập nhật note với danh sách order_code trước khi confirm
            if order_codes_in_detail:
                order_codes_str = ", ".join(order_codes_in_detail)
                if picking.note:
                    picking.note += f"\nĐơn gốc: {order_codes_str}"
                else:
                    picking.note = f"Đơn gốc: {order_codes_str}"
            
            picking.action_confirm()
            _logger.info("✅ Đã tạo phiếu nhập kho %s cho đơn trả %s | order_codes: %s", 
                        picking.name, refno, ", ".join(order_codes_in_detail) or "N/A")
            return True
        else:
            picking.unlink()
            _logger.warning("⚠️ Không có sản phẩm hợp lệ, đã xóa phiếu nhập kho cho đơn %s", refno)
            return False

    def _fetch_return_detail(self, refid, headers, misa_utils):
        """Lấy chi tiết đơn hàng trả về từ API detail_full với optimization
        
        ⚠️ QUAN TRỌNG: Phải dùng detail_full để lấy order_code chính xác
        - order_code trong sa_return_detail là mã đơn gốc CHÍNH XÁC cho từng sản phẩm
        - other_sys_order_code ở master record có thể khác (là mã marketplace)
        - Mỗi sản phẩm trong đơn trả có thể đến từ các đơn gốc khác nhau
        
        Tối ưu để tránh timeout:
        1. Chỉ lấy Details minimal (sa_return_detail), bỏ hết Links
        2. Tăng timeout lên 90s
        3. Bổ sung headers đầy đủ để tránh backend "kẹt"
        4. Bỏ wesign_document, pu_invoice, in_inward, inv_bot_reference
        """
        
        import json
        import base64
        
        # Tạo request payload TỐI THIỂU - chỉ lấy detail, bỏ hết Links
        req_payload = [{
            "Type": "sa_return",
            "Key": refid,
            "RefType": 3040,
            "RefTypeCategory": 354,
            "Details": [
                {
                    "Type": "sa_return_detail",
                    "Alias": "detail",
                    "View": "view_sa_return_detail"
                }
                # Bỏ wesign_document để giảm tải
            ],
            "Links": []  # Bỏ hết pu_invoice, in_inward, inv_bot_reference
        }]
        
        # Encode request thành base64
        req_json = json.dumps(req_payload, separators=(',', ':'))
        req_base64 = base64.b64encode(req_json.encode('utf-8')).decode('utf-8')
        
        detail_url = f"https://actapp.misa.vn/g2/api/sa/v1/sa_return/detail_full?req={req_base64}"
        
        try:
            _logger.info("🔄 Đang gọi detail_full (với full context + cookies) cho đơn %s...", refid)
            _logger.debug("📋 Headers gửi đi: %s", {k: v[:50] + '...' if len(str(v)) > 50 else v 
                                                     for k, v in headers.items()})
            
            # headers đã có ĐẦY ĐỦ từ get_default_headers():
            # - Authorization Bearer token
            # - X-MISA-Context (TenantId, BranchId, DatabaseId, SessionId, UserId...)
            # - Cookie (tid, x-sessionid, dbid, env, cf_clearance)
            # - Referer, Origin, X-Device
            # → Backend MISA sẽ KHÔNG bị "kẹt" như trước
            
            import time
            start_time = time.time()
            
            response = requests.get(
                detail_url,
                headers=headers,  # Dùng trực tiếp headers từ get_default_headers
                timeout=90  # Timeout 90s (thực tế sẽ nhanh hơn nhiều khi có đủ context)
            )
            
            elapsed = time.time() - start_time
            _logger.info("⏱️ detail_full API phản hồi sau %.2f giây", elapsed)
            
            if response.status_code != 200:
                _logger.error("❌ detail_full API trả về HTTP %s cho đơn %s", 
                            response.status_code, refid)
                return None
            
            result = response.json()
            if not result.get("Success"):
                _logger.error("❌ detail_full API Success=False cho đơn %s", refid)
                return None
            
            # Lấy sa_return_detail array (có order_code)
            detail_data = result.get("Data", {}).get("sa_return_detail", [])
            if not detail_data:
                _logger.warning("⚠️ Không có sa_return_detail cho đơn %s", refid)
                return None
            
            _logger.info("✅ Lấy được %s dòng chi tiết (với order_code) cho đơn %s", 
                        len(detail_data), refid)
            
            return detail_data
                
        except requests.exceptions.Timeout:
            _logger.error("❌ Timeout (>90s) khi gọi detail_full cho đơn %s", refid)
            _logger.warning("💡 Gợi ý: API detail_full quá nặng, có thể backend MISA đang chậm")
            return None
        except Exception as e:
            _logger.exception("❌ Lỗi khi gọi detail_full cho đơn %s: %s", refid, e)
            return None

    def _create_stock_move(self, picking, line, location, odoo_utils):
        """Tạo stock move từ dòng chi tiết đơn trả
        
        Args:
            picking: stock.picking record
            line: dict - dòng chi tiết từ API detail_full (sa_return_detail)
            location: stock.location record
            odoo_utils: helper class
        """
        
        product_code = line.get("inventory_item_code", "").strip()
        product_name = line.get("description", "").strip()
        qty = float(line.get("quantity", 0))
        unit_name = line.get("unit_name", "Cái").strip()
        price = float(line.get("unit_price", 0))
        
        # Lấy order_code từ detail line (MỖI SẢN PHẨM có thể từ đơn gốc khác nhau)
        order_code = line.get("order_code", "").strip()
        
        # Log order_code cho từng sản phẩm
        if order_code:
            _logger.info("📦 order_code=%s | sản phẩm=%s | qty=%s", order_code, product_code, qty)
        else:
            _logger.warning("⚠️ Thiếu order_code | sản phẩm=%s | qty=%s", product_code, qty)
        
        if not product_code or qty <= 0:
            _logger.warning("⏭️ Bỏ qua dòng không hợp lệ: code=%s, qty=%s", product_code, qty)
            return
        
        # Tạo hoặc lấy sản phẩm
        product = odoo_utils._get_or_create_product(
            code=product_code,
            name=product_name,
            unit_name=unit_name,
            cost=price,
            purchase_ok=True,
            sale_ok=True
        )
        
        if not product:
            _logger.warning("❌ Không tạo được sản phẩm %s", product_code)
            return
        
        # Tạo stock move - chỉ có thông tin sản phẩm
        # (order_code đã lưu ở picking.note)
        move_vals = {
            "name": product_name or product_code,
            "product_id": product.id,
            "product_uom_qty": qty,
            "product_uom": product.uom_id.id,
            "picking_id": picking.id,
            "location_id": picking.location_id.id,
            "location_dest_id": location.id,
        }
        
        self.env["stock.move"].create(move_vals)
        _logger.info("✅ Đã tạo move cho sản phẩm %s (qty=%s)", product_code, qty)
