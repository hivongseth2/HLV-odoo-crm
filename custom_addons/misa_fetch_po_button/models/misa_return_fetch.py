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
        
        # Lấy order_code từ API detail_full (timeout=60s để chắc chắn)
        order_code = self._fetch_return_order_code(refid, headers)
        if order_code:
            _logger.info("📋 Lấy được order_code: %s cho đơn trả %s", order_code, refno)
        else:
            _logger.info("⏭️  Không lấy được order_code cho đơn %s", refno)
        
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
        
        # Thêm ghi chú nếu có
        if journal_memo:
            picking_vals['note'] = f"Lý do trả: {journal_memo}"
        
        # Thêm order_code nếu có
        if order_code:
            picking_vals['note'] = f"{picking_vals.get('note', '')}\nMã đơn hàng: {order_code}".strip()
        
        picking = self.env["stock.picking"].create(picking_vals)
        
        # Tạo các dòng move từ detail_data (PageData)
        for line in detail_data:
            self._create_stock_move(picking, line, location, odoo_utils)
        
        # Xác nhận phiếu nhập kho
        if picking.move_ids_without_package:
            picking.action_confirm()
            _logger.info("✅ Đã tạo phiếu nhập kho %s cho đơn trả %s", picking.name, refno)
            return True
        else:
            picking.unlink()
            _logger.warning("⚠️ Không có sản phẩm hợp lệ, đã xóa phiếu nhập kho cho đơn %s", refno)
            return False

    def _fetch_return_order_code(self, refid, headers):
        """Lấy order_code từ API detail_full - timeout 60s"""
        
        import base64
        import json
        
        try:
            # Xây dựng request data
            request_data = [
                {
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
                    ],
                    "Links": []
                }
            ]
            
            # Encode thành base64
            req_json = json.dumps(request_data, separators=(',', ':'))
            req_encoded = base64.b64encode(req_json.encode()).decode()
            
            detail_full_url = f"https://actapp.misa.vn/g2/api/sa/v1/sa_return/detail_full?req={req_encoded}"
            
            # Gọi API với timeout 60 giây
            response = requests.get(detail_full_url, headers=headers, timeout=60)
            
            if response.status_code != 200:
                _logger.warning("❌ API detail_full HTTP %s cho đơn %s", response.status_code, refid)
                return ""
            
            result = response.json()
            if result.get("Success"):
                details = result.get("Data", {}).get("sa_return_detail", [])
                if details and isinstance(details, list) and len(details) > 0:
                    order_code = details[0].get("order_code", "")
                    return order_code
            
            return ""
                
        except requests.exceptions.Timeout:
            _logger.warning("⏱️  API detail_full timeout (60s) cho đơn %s, bỏ qua order_code", refid)
            return ""
        except Exception as e:
            _logger.warning("⚠️  Lỗi lấy order_code từ API detail_full: %s", str(e)[:100])
            return ""

    def _fetch_return_detail(self, refid, headers, misa_utils):
        """Lấy chi tiết đơn hàng trả về"""
        
        # Tạo payload cho API get_paging_detail
        detail_payload = {
            "columns": [2157, 2818, 1355, 4670, 1195, 5274, 3870, 1065, 5683, 5279, 308, 5364, 5350, 5347, 4405, 3404, 5476, 5575, 2358],
            "sort": '[{"property":4555,"desc":false,"data_type":4,"operand":1}]',
            "filter": [
                {
                    "property": 3993,
                    "operator": 7,
                    "operand": 1,
                    "value": refid,
                    "data_type": 10
                }
            ],
            "pageIndex": 1,
            "pageSize": 20,
            "useSp": False,
            "view": 54,
            "summaryColumns": [3870, 3488, 308, 5350],
            "loadMode": 2
        }
        
        # Gọi API get_paging_detail
        detail_url = "https://actapp.misa.vn/g2/api/sa/v1/sa_return/get_paging_detail"
        
        try:
            response = misa_utils._fetch_with_retry(detail_url, headers, detail_payload)
            
            if response.status_code != 200:
                _logger.error("❌ Không lấy được chi tiết đơn trả %s: HTTP %s", 
                            refid, response.status_code)
                return None
            
            result = response.json()
            if result.get("Success"):
                # Trả về PageData thay vì toàn bộ Data
                return result.get("Data", {}).get("PageData", [])
            else:
                _logger.error("❌ API trả về Success=False cho đơn %s", refid)
                return None
                
        except requests.exceptions.Timeout:
            _logger.error("❌ Timeout khi gọi API chi tiết đơn trả %s", refid)
            return None
        except Exception as e:
            _logger.exception("❌ Lỗi khi gọi API chi tiết đơn trả %s: %s", refid, e)
            return None

    def _create_stock_move(self, picking, line, location, odoo_utils):
        """Tạo stock move từ dòng chi tiết đơn trả"""
        
        product_code = line.get("inventory_item_code", "").strip()
        product_name = line.get("description", "").strip()
        qty = float(line.get("quantity", 0))
        unit_name = line.get("unit_name", "Cái").strip()
        price = float(line.get("unit_price", 0))
        
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
        
        # Tạo stock move
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
