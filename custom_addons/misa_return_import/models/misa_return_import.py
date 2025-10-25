from odoo import models, fields, _
import logging
import json
import base64
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
                },
                {
                    "Type": "wesign_document",
                    "Alias": "wesign_document",
                    "ForeignKey": "refid",
                    "Mode": "View"
                }
            ],
            "Links": [
                {
                    "Type": "pu_invoice",
                    "RefType": 3403,
                    "RefTypeCategory": 0,
                    "UseSameKeyWithMaster": False,
                    "KeyColumnInMaster": "pu_invoice_refid"
                },
                {
                    "Type": "in_inward",
                    "RefType": 2013,
                    "RefTypeCategory": 201,
                    "UseSameKeyWithMaster": False,
                    "KeyColumnInMaster": "in_inward_refid"
                },
                {
                    "Type": "inv_bot_reference",
                    "RefType": 0,
                    "RefTypeCategory": 0
                }
            ]
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
        
        # Chuyển đổi ngày sang UTC
        date_from_utc = datetime.combine(self.date_from, datetime.min.time()) - timedelta(hours=7)
        date_to_utc = datetime.combine(self.date_to, datetime.max.time()) - timedelta(hours=7)
        
        # Mapping kho
        stock_mapping = {
            "HCM": "TSN/Stock",
            "BENCAM": "KBC/Tồn kho",
            "HIENDUC": "KHD/Tồn kho",
            "HCM_SHOWROOM": "TSNSR/Stock"
        }
        
        # Payload để lấy danh sách phiếu trả hàng
        # Sử dụng format chính xác từ MISA
        payload = {
            "filter": [
                {
                    "property": 3972,  # refdate (giống như PO)
                    "value": date_from_utc.isoformat() + "Z",
                    "operator": 10,  # >=
                    "operand": 1,
                    "data_type": 3
                },
                {
                    "property": 3972,  # refdate
                    "value": date_to_utc.isoformat() + "Z",
                    "operator": 12,  # <=
                    "operand": 1,
                    "data_type": 3
                }
            ],
            "loadMode": 2,
            "pageIndex": 1,
            "pageSize": 20,
            "sort": "[{\"property\":3654,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":4018,\"desc\":true,\"data_type\":1,\"operand\":1}]",
            "summaryColumns": [5126, 5068, 5141, 5039],
            "useSp": False,
            "view": 64  # View ID cho sa_return
        }
        
        page_index = 1
        total_created = 0
        total_skipped = 0
        
        _logger.info("🔍 Payload để lấy phiếu trả hàng: %s", json.dumps(payload, indent=2))
        
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
                    
                    # Lấy chi tiết phiếu trả hàng
                    req_param = self._decode_detail_request(refid)
                    detail_url = f"https://actapp.misa.vn/g2/api/sa/v1/sa_return/detail_full?req={req_param}"
                    
                    _logger.info("🔍 Đang lấy chi tiết phiếu %s (refid: %s)", refno, refid)
                    
                    # Sử dụng GET request cho detail_full
                    detail_response = requests.get(detail_url, headers=headers, timeout=30)
                    
                    if detail_response.status_code != 200:
                        _logger.warning("❌ Không lấy được chi tiết phiếu %s (HTTP %s)", 
                                      refno, detail_response.status_code)
                        total_skipped += 1
                        continue
                    
                    try:
                        detail_json = detail_response.json()
                    except Exception as json_err:
                        _logger.error("❌ Lỗi parse JSON chi tiết phiếu %s: %s", refno, json_err)
                        total_skipped += 1
                        continue
                    
                    detail_data = detail_json.get("Data", {})
                    
                    # Lấy thông tin master từ sa_return
                    sa_return_master = detail_data.get("sa_return", [])
                    master_info = sa_return_master[0] if sa_return_master else {}
                    
                    # Lấy thông tin bổ sung
                    journal_memo = master_info.get("journal_memo", "")  # Lý do trả hàng
                    employee_name = master_info.get("employee_name", "")
                    employee_code = master_info.get("employee_code", "")
                    total_amount = master_info.get("total_amount", 0.0)
                    total_vat_amount = master_info.get("total_vat_amount", 0.0)
                    
                    # Lấy thông tin phiếu nhập kho liên quan (nếu có)
                    in_inward_list = detail_data.get("in_inward", [])
                    in_inward_info = in_inward_list[0] if in_inward_list else {}
                    in_inward_refno = in_inward_info.get("refno_finance", "")
                    
                    # Lấy thông tin hóa đơn mua (nếu có)
                    pu_invoice_list = detail_data.get("pu_invoice", [])
                    pu_invoice_info = pu_invoice_list[0] if pu_invoice_list else {}
                    pu_invoice_refno = pu_invoice_info.get("refno_finance", "") if pu_invoice_info else ""
                    
                    # Log thông tin bổ sung
                    _logger.info("📝 Lý do trả hàng: %s", journal_memo)
                    _logger.info("👤 Nhân viên: %s (%s)", employee_name, employee_code)
                    if in_inward_refno:
                        _logger.info("📦 Phiếu nhập kho liên quan: %s", in_inward_refno)
                    
                    # Lấy chi tiết sản phẩm
                    lines = detail_data.get("sa_return_detail", [])
                    
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
                    if in_inward_refno:
                        note_parts.append(f"Phiếu nhập kho MISA: {in_inward_refno}")
                    if pu_invoice_refno:
                        note_parts.append(f"Hóa đơn mua: {pu_invoice_refno}")
                    
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
                        order_code = line.get("order_code", "")  # Mã đơn hàng gốc
                        sa_voucher_no = line.get("sa_voucher_no", "")  # Mã phiếu bán hàng
                        outward_refno = line.get("outward_refno_finance", "")  # Mã phiếu xuất kho
                        vat_rate = line.get("vat_rate", 0.0)
                        stock_name = line.get("stock_name", "")
                        
                        if qty <= 0:
                            _logger.warning("⚠️ Bỏ qua dòng với số lượng <= 0: %s", product_code)
                            continue
                        
                        product = self._get_or_create_product(product_code, product_name, unit_name, price)
                        
                        # Tạo description cho move
                        move_description = product_name
                        if order_code:
                            move_description += f" | ĐH: {order_code}"
                        if sa_voucher_no:
                            move_description += f" | PBH: {sa_voucher_no}"
                        if outward_refno:
                            move_description += f" | PXK: {outward_refno}"
                        
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
                        
                        _logger.info("  ✓ %s x%.2f (ĐH: %s, VAT: %.1f%%)", 
                                   product_code, qty, order_code or "N/A", vat_rate)
                    
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
