from odoo import models, fields, _
import logging
import json
import base64
import time
from datetime import datetime, timedelta, timezone
import requests

_logger = logging.getLogger(__name__)

class MisaReturnImport(models.TransientModel):
    _name = "misa.return.import"
    _description = "MISA Return Import"
    
    date_from = fields.Date(string="Từ ngày", required=True)
    date_to = fields.Date(string="Đến ngày", required=True)
    auto_validate = fields.Boolean(
        string="Tự động xác nhận phiếu", 
        default=False,
        help="Nếu bật, phiếu nhập kho sẽ tự động được xác nhận sau khi tạo"
    )
    
    def _to_naive_utc(self, dt_str: str):
        """'2025-10-16T00:00:00.000+07:00' -> 2025-10-15 17:00:00 (naive UTC)"""
        if not dt_str:
            return False
        aware = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return aware.astimezone(timezone.utc).replace(tzinfo=None)
    
    def _get_or_create_partner(self, name, code=None, tax_code=None, address=None):
        """Tìm hoặc tạo mới đối tác (partner) dựa trên tên và thông tin bổ sung."""
        name = name.strip() if name else "Unknown"
        
        # Tìm theo tên trước
        partner = self.env["res.partner"].search([("name", "=", name)], limit=1)
        
        if not partner:
            partner_vals = {
                "name": name,
                "customer_rank": 1,  # Đây là khách hàng trả hàng
            }
            if code:
                partner_vals['ref'] = code
            if tax_code:
                partner_vals['vat'] = tax_code
            if address:
                partner_vals['street'] = address
            
            partner = self.env["res.partner"].create(partner_vals)
            _logger.info("✅ Tạo đối tác mới: %s", name)
        else:
            # Cập nhật thông tin nếu thiếu
            update_vals = {}
            if code and not partner.ref:
                update_vals['ref'] = code
            if tax_code and not partner.vat:
                update_vals['vat'] = tax_code
            if address and not partner.street:
                update_vals['street'] = address
            
            if update_vals:
                partner.write(update_vals)
                _logger.info("🔄 Cập nhật thông tin đối tác: %s", name)
        
        return partner
    
    def _get_or_create_product(self, code, name, unit_name, price=0.0):
        """Tìm hoặc tạo mới sản phẩm."""
        code = code.strip() if code else "UNKNOWN"
        name = name.strip() if name else code
        
        product = self.env["product.product"].search([("default_code", "=", code)], limit=1)
        
        if product:
            _logger.info("🔁 Tìm thấy sản phẩm: %s", code)
            return product
        
        # Tạo/lấy UoM
        uom = self._get_or_create_uom(unit_name)
        
        # Tạo sản phẩm mới
        tmpl = self.env["product.template"].create({
            "name": name,
            "default_code": code,
            "type": "product",  # Sản phẩm lưu kho
            "uom_id": uom.id,
            "uom_po_id": uom.id,
            "standard_price": price,
            "purchase_ok": True,
            "sale_ok": True,
            "is_storable": True,
        })
        
        _logger.info("🆕 Tạo sản phẩm mới: %s", code)
        return tmpl.product_variant_id
    
    def _get_or_create_uom(self, name):
        """Tìm hoặc tạo mới đơn vị tính (UoM)."""
        name = name.strip().title() if name else "Cái"
        
        uom = self.env['uom.uom'].search([('name', '=', name)], limit=1)
        if uom:
            return uom
        
        # Tìm category 'Unit' hoặc tạo mới
        cat = self.env['uom.category'].search([('name', 'ilike', 'Unit')], limit=1)
        if not cat:
            cat = self.env['uom.category'].create({'name': 'Unit'})
        
        # Kiểm tra xem đã có reference UoM chưa
        ref_uom = self.env['uom.uom'].search([
            ('category_id', '=', cat.id),
            ('uom_type', '=', 'reference')
        ], limit=1)
        
        uom_type = 'reference' if not ref_uom else 'smaller'
        
        return self.env['uom.uom'].create({
            'name': name,
            'category_id': cat.id,
            'uom_type': uom_type,
            'factor_inv': 1.0,
            'rounding': 1.0,
        })
    
    def _decode_detail_request(self, refid, reftype=3540, reftype_category=354):
        """
        Tạo request parameter cho API detail_full.
        Encode base64 theo format MISA yêu cầu.
        OPTIMIZED: Chỉ lấy sa_return và sa_return_detail, bỏ Links để tăng tốc độ.
        """
        request_obj = [{
            "Type": "sa_return",
            "Key": refid,
            "RefType": reftype,
            "RefTypeCategory": reftype_category,
            "Details": [
                {
                    "Type": "sa_return_detail",
                    "Alias": "detail",
                    "View": "view_sa_return_detail"
                }
            ]
            # Bỏ Links và wesign_document để giảm tải API
        }]
        
        json_str = json.dumps(request_obj, separators=(',', ':'))
        encoded = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
        return encoded
    
    def action_import_returns(self):
        """Import phiếu trả hàng từ MISA."""
        misa_utils = self.env['misa.api.utils']
        misa_config = self.env['misa.config']
        
        # Lấy token
        access_token = misa_utils._get_misa_token()
        headers = misa_config.get_default_headers(access_token)
        
        # Chuyển đổi ngày sang UTC (MISA dùng timezone +07:00 cho VN)
        # date_from: 00:00:00 VN+7 -> UTC-7
        # date_to: 23:59:59 VN+7 -> UTC-7, nhưng dùng ngày hôm sau 00:00:00 để tránh microseconds
        vn_tz = timezone(timedelta(hours=7))
        date_from_vn = datetime.combine(self.date_from, datetime.min.time()).replace(tzinfo=vn_tz)
        date_to_vn = datetime.combine(self.date_to + timedelta(days=1), datetime.min.time()).replace(tzinfo=vn_tz)
        
        date_from_utc = date_from_vn.astimezone(timezone.utc).replace(tzinfo=None)
        date_to_utc = date_to_vn.astimezone(timezone.utc).replace(tzinfo=None)
        
        # Mapping kho
        stock_mapping = {
            "HCM": "TSN/Stock",
            "BENCAM": "KBC/Tồn kho",
            "HIENDUC": "KHD/Tồn kho",
            "HCM_SHOWROOM": "TSNSR/Stock"
        }
        
        # Payload để lấy danh sách phiếu trả hàng
        # Sử dụng format chính xác từ MISA
        # Format datetime: YYYY-MM-DDTHH:MM:SSZ (không có microseconds)
        payload = {
            "filter": [
                {
                    "property": 3972,  # refdate (giống như PO)
                    "value": date_from_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "operator": 10,  # >=
                    "operand": 1,
                    "data_type": 3
                },
                {
                    "property": 3972,  # refdate
                    "value": date_to_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "operator": 12,  # <=
                    "operand": 1,
                    "data_type": 3
                }
            ],
            "loadMode": 2,  # Mode 2: chỉ lấy master, detail phải call riêng
            "pageIndex": 1,
            "pageSize": 20,  # Tăng lên 20 vì get_paging_detail nhanh hơn detail_full
            "sort": "[{\"property\":3654,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":4018,\"desc\":true,\"data_type\":1,\"operand\":1}]",
            "summaryColumns": [5126, 5068, 5141, 5039],
            "useSp": False,
            "view": 64  # View ID cho sa_return
        }
        
        page_index = 1
        total_created = 0
        total_skipped = 0
        
        while True:
            payload["pageIndex"] = page_index
            _logger.info("📄 Đang fetch trang %s phiếu trả hàng...", page_index)
            
            response = misa_utils._fetch_with_retry(
                "https://actapp.misa.vn/g2/api/sa/v1/sa_return/paging_filter_v2",
                headers, payload
            )
            
            _logger.info("📥 Response status: %s", response.status_code)
            if response.status_code != 200:
                try:
                    error_data = response.json()
                    _logger.error("❌ API Error: %s", json.dumps(error_data, indent=2))
                except:
                    _logger.error("❌ Response text: %s", response.text[:500])
                _logger.warning("❌ Gọi API thất bại ở trang %s", page_index)
                break
            
            # Parse response
            try:
                response_data = response.json()
            except Exception as json_err:
                _logger.error("❌ Lỗi parse JSON response: %s", json_err)
                break
            
            # Kiểm tra Success flag
            if not response_data.get("Success", True):
                _logger.error("❌ MISA API trả về lỗi: %s", response_data.get("SystemMessage"))
                _logger.error("   Error Code: %s, SubCode: %s", 
                            response_data.get("Code"), response_data.get("SubCode"))
                _logger.error("   Exception ID: %s", response_data.get("ExceptionID"))
                break
            
            page_data = response_data.get("Data", {}).get("PageData", [])
            if not page_data:
                _logger.info("✅ Hết dữ liệu, dừng ở trang %s", page_index)
                break
            
            # Xử lý từng phiếu trả hàng
            for return_doc in page_data:
                refid = return_doc.get("refid")
                refno = return_doc.get("refno_finance", "BTL-UNKNOWN")
                
                # Kiểm tra đã tồn tại chưa (dựa vào origin)
                existing_picking = self.env["stock.picking"].search([
                    ("origin", "=", f"MISA-{refno}")
                ], limit=1)
                
                if existing_picking:
                    _logger.info("⏭️ Bỏ qua phiếu %s đã tồn tại", refno)
                    total_skipped += 1
                    continue
                
                # Lấy thông tin chi tiết
                try:
                    customer_name = return_doc.get("account_object_name", "Unknown Customer")
                    customer_code = return_doc.get("account_object_code", "")
                    customer_tax = return_doc.get("account_object_tax_code", "")
                    customer_address = return_doc.get("account_object_address", "")
                    
                    partner = self._get_or_create_partner(
                        customer_name, 
                        customer_code, 
                        customer_tax, 
                        customer_address
                    )
                    
                    # Lấy chi tiết phiếu trả hàng qua API get_paging_detail (NHANH HƠN detail_full)
                    # API này trả về chi tiết dòng sản phẩm nhưng KHÔNG có order_code
                    # TODO: Sẽ tìm cách lấy order_code sau
                    detail_url = "https://actapp.misa.vn/g2/api/sa/v1/sa_return/get_paging_detail"
                    
                    detail_payload = {
                        "refID": refid,
                        "refType": 3540,
                        "pageIndex": 1,
                        "pageSize": 100  # Lấy hết detail trong 1 lần
                    }
                    
                    _logger.info("🔍 Đang lấy chi tiết phiếu %s (get_paging_detail)", refno)
                    
                    try:
                        detail_response = misa_utils._fetch_with_retry(detail_url, headers, detail_payload)
                        
                        if detail_response.status_code != 200:
                            _logger.warning("❌ Không lấy được chi tiết phiếu %s, bỏ qua", refno)
                            total_skipped += 1
                            continue
                        
                        detail_json = detail_response.json()
                        detail_data = detail_json.get("Data", {})
                        
                        # Lấy PageData chứa danh sách dòng chi tiết
                        lines = detail_data.get("PageData", [])
                        
                    except Exception as e:
                        _logger.error("❌ Lỗi lấy chi tiết phiếu %s: %s", refno, str(e))
                        total_skipped += 1
                        continue
                    
                    # Lấy thông tin bổ sung từ return_doc (PageData của paging_filter_v2)
                    # API get_paging_detail chỉ trả về detail lines, không có master info
                    journal_memo = return_doc.get("journal_memo", "")
                    employee_name = return_doc.get("employee_name", "")
                    employee_code = return_doc.get("employee_code", "")
                    total_amount = return_doc.get("total_amount", 0.0)
                    total_vat_amount = return_doc.get("total_vat_amount", 0.0)
                    
                    # Log thông tin bổ sung
                    _logger.info("📝 Lý do trả hàng: %s", journal_memo)
                    _logger.info("👤 Nhân viên: %s (%s)", employee_name, employee_code)
                    
                    # lines đã được lấy từ PageData ở trên
                    
                    if not lines:
                        _logger.warning("⚠️ Phiếu %s không có dòng chi tiết", refno)
                        total_skipped += 1
                        continue
                    
                    # Xác định kho từ dòng đầu tiên
                    stock_code = lines[0].get("stock_code", "").strip().replace(" ", "").upper()
                    
                    if stock_code not in stock_mapping:
                        _logger.warning("📛 Kho %s không trong mapping, bỏ phiếu %s", stock_code, refno)
                        total_skipped += 1
                        continue
                    
                    location_name = stock_mapping[stock_code]
                    location = self.env['stock.location'].search([
                        ('complete_name', '=', location_name)
                    ], limit=1)
                    
                    if not location:
                        _logger.warning("❌ Không tìm thấy location %s", location_name)
                        total_skipped += 1
                        continue
                    
                    # Tìm warehouse và picking type
                    warehouse = self.env['stock.warehouse'].search([
                        ('view_location_id', '=', location.location_id.id)
                    ], limit=1)
                    
                    if not warehouse:
                        _logger.warning("❌ Không tìm thấy warehouse cho kho %s", stock_code)
                        total_skipped += 1
                        continue
                    
                    picking_type = warehouse.in_type_id  # Loại phiếu nhập kho
                    
                    # Lấy ngày phiếu
                    refdate_str = return_doc.get("refdate") or return_doc.get("posted_date")
                    scheduled_date = self._to_naive_utc(refdate_str) if refdate_str else fields.Datetime.now()
                    
                    # Tạo note bao gồm thông tin bổ sung
                    note_parts = []
                    if journal_memo:
                        note_parts.append(f"Lý do: {journal_memo}")
                    if employee_name:
                        note_parts.append(f"NV xử lý: {employee_name} ({employee_code})")
                    
                    note = "\n".join(note_parts) if note_parts else ""
                    
                    # Tạo phiếu nhập kho (stock.picking)
                    picking_vals = {
                        "partner_id": partner.id,
                        "picking_type_id": picking_type.id,
                        "location_id": partner.property_stock_customer.id,  # Từ khách hàng
                        "location_dest_id": location.id,  # Về kho
                        "origin": f"MISA-{refno}",
                        "scheduled_date": scheduled_date,
                        "note": note,  # Thêm note chứa thông tin bổ sung
                    }
                    
                    picking = self.env["stock.picking"].create(picking_vals)
                    
                    # Tạo các dòng move
                    for line in lines:
                        product_code = line.get("inventory_item_code", "UNKNOWN").strip()
                        product_name = line.get("description", product_code).strip()
                        unit_name = line.get("unit_name", "Cái").strip()
                        qty = float(line.get("quantity", 0))
                        price = float(line.get("unit_price", 0))
                        
                        # Lấy thông tin bổ sung từ dòng
                        # NOTE: get_paging_detail KHÔNG có order_code, outward_refno_finance
                        # Chỉ có sa_voucher_no (mã phiếu bán hàng)
                        sa_voucher_no = line.get("sa_voucher_no", "")  # Mã phiếu bán hàng
                        vat_rate = line.get("vat_rate", 0.0)
                        stock_code_line = line.get("stock_code", "")
                        
                        if qty <= 0:
                            _logger.warning("⚠️ Bỏ qua dòng với số lượng <= 0: %s", product_code)
                            continue
                        
                        product = self._get_or_create_product(product_code, product_name, unit_name, price)
                        
                        # Tạo description cho move (chỉ có PBH, chưa có ĐH và PXK)
                        move_description = product_name
                        if sa_voucher_no:
                            move_description += f" | PBH: {sa_voucher_no}"
                        # TODO: Thêm order_code từ detail_full sau
                        
                        # Tạo stock.move
                        self.env["stock.move"].create({
                            "name": move_description,
                            "product_id": product.id,
                            "product_uom_qty": qty,
                            "product_uom": product.uom_id.id,
                            "picking_id": picking.id,
                            "location_id": picking.location_id.id,
                            "location_dest_id": picking.location_dest_id.id,
                        })
                        
                        _logger.info("  ✓ %s x%.2f (PBH: %s, VAT: %.1f%%)", 
                                   product_code, qty, sa_voucher_no or "N/A", vat_rate)
                    
                    # Log thông tin tổng hợp
                    _logger.info("✅ Đã tạo phiếu nhập kho trả hàng: %s (ID: %s)", refno, picking.id)
                    _logger.info("   💰 Tổng tiền: {:,.0f} VND (VAT: {:,.0f} VND)".format(
                        total_amount, total_vat_amount))
                    _logger.info("   📦 Số dòng sản phẩm: %d", len(lines))
                    
                    # Tự động xác nhận nếu được bật
                    if self.auto_validate:
                        try:
                            # Set số lượng thực tế = số lượng dự kiến
                            for move in picking.move_ids_without_package:
                                move.quantity = move.product_uom_qty
                            
                            # Xác nhận phiếu
                            picking.button_validate()
                            _logger.info("✅ Đã tự động xác nhận phiếu %s", refno)
                        except Exception as validate_err:
                            _logger.warning("⚠️ Không thể tự động xác nhận phiếu %s: %s", 
                                          refno, validate_err)
                    
                    total_created += 1
                    
                except Exception as e:
                    _logger.exception("❌ Lỗi xử lý phiếu %s: %s", refno, e)
                    total_skipped += 1
                    continue
            
            page_index += 1
        
        # Thông báo kết quả
        message = f"✅ Hoàn thành import phiếu trả hàng!\n"
        message += f"- Đã tạo: {total_created} phiếu\n"
        message += f"- Đã bỏ qua: {total_skipped} phiếu"
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Import hoàn tất'),
                'message': message,
                'type': 'success',
                'sticky': False,
            }
        }
