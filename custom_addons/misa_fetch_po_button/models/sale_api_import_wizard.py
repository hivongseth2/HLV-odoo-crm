import requests
from odoo import models, fields, api, _
from datetime import datetime, timedelta
from dateutil import parser  # để xử lý ISO datetime
import logging
from dateutil.parser import parse
from collections import defaultdict
import uuid
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class SaleApiImportWizard(models.TransientModel):
    _name = 'sale.api.import.wizard'
    _description = 'Import Sale Orders from MISA API'

    from_date = fields.Date(string="Từ ngày", required=True)
    to_date = fields.Date(string="Đến ngày", required=True)
    
    def _force_cancel_sale_order(self, so, revenue_status_id, status):
        """
        Hủy SO 'so' nếu trạng thái MISA là 'Từ chối ghi' (ID=4 hoặc text 'từ chối ghi').
        Chỉ dùng field/method sẵn có của sale.order, không thêm attribute lạ.
        """
        txt = (status or "").strip().lower()
        if not (revenue_status_id == 4 or txt == "từ chối ghi"):
            return False

        _logger.info("🚫 SO %s: MISA 'Từ chối ghi' → force-cancel", so.name)

        # 1) Hủy các picking còn mở
        for p in (so.picking_ids or []):
            st = p.state
            if st in ('waiting', 'confirmed', 'assigned'):
                try:
                    p.sudo().action_cancel()
                except Exception as pe:
                    _logger.warning("Không thể cancel picking %s: %s", p.name, pe)
            elif st == 'draft':
                try:
                    p.sudo().unlink()
                except Exception as pe:
                    _logger.warning("Không thể xóa picking draft %s: %s", p.name, pe)

        # 2) Hủy invoice chưa ghi sổ; nếu đã posted → chặn
        for inv in (so.invoice_ids or []):
            st = getattr(inv, 'state', None)
            if st in ('draft', 'cancel'):
                try:
                    if hasattr(inv, 'button_cancel'):
                        inv.sudo().button_cancel()
                    elif hasattr(inv, 'action_cancel'):
                        inv.sudo().action_cancel()
                except Exception as ie:
                    _logger.warning("Không thể hủy invoice %s: %s", getattr(inv, 'name', 'n/a'), ie)
            elif st == 'posted':
                # DỪNG lại theo đúng nghiệp vụ
                raise UserError(_("Đơn có hóa đơn đã ghi sổ (%s). Hãy hủy/bỏ ghi sổ trước khi hủy đơn.") % inv.name)

        # 3) Hủy SO. Nếu action_cancel() lỗi → fallback hủy dòng rồi set state=cancel
        if so.state not in ('cancel', 'done'):
            try:
                so.sudo().action_cancel()
            except Exception as e1:
                _logger.warning("action_cancel thất bại: %s → fallback _action_cancel + write(cancel)", e1)
                if hasattr(so.order_line, '_action_cancel'):
                    try:
                        so.order_line.sudo()._action_cancel()
                    except Exception:
                        pass
                so.sudo().write({'state': 'cancel'})

        # 4) Kiểm tra lại trạng thái bằng cách re-browse
        state_now = self.env['sale.order'].sudo().browse(so.id).state
        if state_now != 'cancel':
            if hasattr(so.order_line, '_action_cancel'):
                try:
                    so.order_line.sudo()._action_cancel()
                except Exception:
                    pass
            so.sudo().write({'state': 'cancel'})
            state_now = self.env['sale.order'].sudo().browse(so.id).state

        if state_now == 'cancel':
            so.message_post(body=_("Phiếu bị hủy khi đồng bộ do trạng thái MISA: Từ chối ghi"))
            return True
        else:
            raise UserError(_("Không thể đưa phiếu về trạng thái hủy. Kiểm tra picking/invoice ràng buộc."))

    
    
    # ================== HELPERS QUY ĐỔI UOM ==================

    def _misa_fetch_conversion_units(self, product_id, headers):
        """
        Gọi Product/DataSubPaging để lấy quy đổi UoM theo đúng payload bạn yêu cầu.
        """
        if not product_id:
            return []
        url = "https://amisapp.misa.vn/crm/g2/api/business/Product/DataSubPaging"

        payload = {
            "Columns": "SUQsQ29udmVyc2lvblVuaXRJRCxDb252ZXJzaW9uVW5pdElEVGV4dCxDb252ZXJzaW9uUmF0ZSxEZXNjcmlwdGlvbixDb252ZXJzaW9uT3BlcmF0b3JJRCxDb252ZXJzaW9uT3BlcmF0b3JJRFRleHQsQ29udmVyc2lvblVuaXRQcmljZTIsQ29udmVyc2lvblVuaXRQcmljZSxDb252ZXJzaW9uVW5pdFByaWNlMSxDb252ZXJzaW9uVW5pdFByaWNlRml4ZWQ=",
            "Sorts": [],
            "Start": 0,
            "Page": 1,
            "PageSize": 20,
            "Filters": [],
            "DefaultTotal": False,
            "IsMappingData": False,
            "MappingValueObject": {
                "MasterID": str(product_id),
                "TableName": "product_conversion_unit",
                "MasterKey": "ProductID",
                "SumColumn": ""
            },
            "IsApproved": False,
            "CustomPagingData": {
                "SubFormConfig": {
                    "ColumnFieldSubForm": "",
                    "ColumnAggregateSubForm": "",
                    "TableName": "product_conversion_unit",
                    "ParentIDKey": "ProductID",
                    "IsBringSerialType": False,
                    "AggregateField": []
                }
            },
            "IsUsedELTS": True,
            "ListGmailPage": [],
            "ListFacebookPage": {},
            "IsListPaging": True,
            "IsGetCache": True,
            "IsCheckInactive": False,
            "IsConverted": False,
            "SessionID": str(uuid.uuid4()),
            "AISearchKeyword": ""
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return data.get("Data", []) or []
        except Exception as e:
            _logger.exception("❗ Lỗi gọi Product/DataSubPaging: %s", e)
            return []

    def _convert_qty_price_to_default_uom(self, product, misa_uom_text, qty, price, misa_product_id, headers):
        """
        Chuyển qty/price từ đơn vị lấy từ MISA (misa_uom_text) về đơn vị mặc định của product (product.uom_id).
        Trả về: (qty_base, price_base, uom_is_default)
        - uom_is_default = True nếu misa_uom_text trùng default (không cần convert)
        """
        default_uom_name = (product.uom_id and product.uom_id.name) or ""
        if not misa_uom_text or misa_uom_text.strip().lower() == default_uom_name.strip().lower():
            return qty, price, True  # không cần đổi

        # Lấy bảng quy đổi theo ProductID
        conversions = self._misa_fetch_conversion_units(misa_product_id, headers) if misa_product_id else []
        # Tìm dòng conversion khớp với UoM của MISA trên line (theo tên)
        conv = next((
            c for c in (conversions or [])
            if (c.get("ConversionUnitIDText") or "").strip().lower() == misa_uom_text.strip().lower()
        ), None)

        if not conv:
            _logger.warning("⚠️ Không tìm thấy mapping UoM cho '%s' -> giữ nguyên số liệu gốc", misa_uom_text)
            return qty, price, False

        try:
            rate = float(conv.get("ConversionRate") or 0) or 0.0
        except Exception:
            rate = 0.0
        try:
            op_id = int(conv.get("ConversionOperatorID") or 1)  # 1=Nhân, 2=Chia
        except Exception:
            op_id = 1

        if rate <= 0:
            _logger.warning("⚠️ ConversionRate không hợp lệ (<=0) cho '%s'", misa_uom_text)
            return qty, price, False

        # Diễn giải:
        # - op_id == 1 (Nhân): "1 Hộp = 60 Cuộn"
        #   Dòng ở Hộp, default là Cuộn -> qty_base = qty * 60; price_base = price / 60
        # - op_id == 2 (Chia): "1 Mét = 1/50 Cuộn"
        #   Dòng ở Mét,  default là Cuộn -> qty_base = qty / 50; price_base = price * 50
        if op_id == 1:
            qty_base = qty * rate
            price_base = price / rate if rate else price
        else:  # op_id == 2 (Chia) hoặc bất kỳ khác coi như "Chia"
            qty_base = qty / rate
            price_base = price * rate

        return qty_base, price_base, False
    
    # ==== Helper lấy VAT ====
    def _get_or_create_vn_vat(self, rate, use='sale'):
        """
        Lấy hoặc tạo thuế VAT Việt Nam với định dạng tên cố định: 'VAT VN X%'.
        Luôn gán country_id = Việt Nam, tax_group_id = 'VAT'.
        """
        Tax = self.env['account.tax'].with_company(self.env.company)
        TaxGroup = self.env['account.tax.group'].with_company(self.env.company)

        rate = float(rate)
        # 🔹 Lấy quốc gia Việt Nam (ưu tiên mã VN, fallback theo tên)
        country_vn = self.env['res.country'].search([('code', '=', 'VN')], limit=1)
        if not country_vn:
            country_vn = self.env['res.country'].search([('name', 'ilike', 'Viet%')], limit=1)

        # 🔹 Tìm / tạo nhóm thuế VAT
        vat_group = TaxGroup.search([
            ('name', 'in', ['VAT', 'Thuế GTGT', 'GTGT']),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not vat_group:
            vat_group = TaxGroup.create({
                'name': 'VAT',
                'company_id': self.env.company.id,
                'country_id': country_vn.id or self.env.company.country_id.id,
                'sequence': 10,
            })

        # 🔹 Tên thuế theo chuẩn VN
        rate_str = str(int(rate)) if float(rate).is_integer() else str(rate)
        vat_name = f'VAT VN {rate_str}%'

        # 🔹 Tìm thuế cùng % trong công ty (ưu tiên theo tên chuẩn)
        tax = Tax.search([
            ('type_tax_use', '=', use),
            ('amount_type', '=', 'percent'),
            ('amount', '=', rate),
            ('company_id', '=', self.env.company.id),
        ], limit=1)

        if tax:
            # Nếu tên đang khác chuẩn => cập nhật lại luôn cho đồng bộ
            if tax.name != vat_name or tax.country_id.code != 'VN':
                tax.write({
                    'name': vat_name,
                    'country_id': country_vn.id or self.env.company.country_id.id,
                    'tax_group_id': vat_group.id,
                })
            return tax

        # 🔹 Nếu chưa có, tạo mới đúng chuẩn
        new_tax = Tax.create({
            'name': vat_name,
            'type_tax_use': use,
            'amount_type': 'percent',
            'amount': rate,
            'company_id': self.env.company.id,
            'price_include': False,
            'country_id': country_vn.id or self.env.company.country_id.id,
            'tax_group_id': vat_group.id,
            'active': True,
        })
        _logger.info("✅ Tạo mới thuế: %s (id=%s)", new_tax.name, new_tax.id)
        return new_tax



    def _tax_ids_from_misa_sale_line(self, l: dict):
        """
        Trả về list tax_id cho dòng SO từ dữ liệu MISA.
        MISA CRM trả: TaxPercentIDText (ví dụ: '8%', '10%', 'KCT')
        """
        kct_markers = {'KCT', 'KHONGCHIU', 'NO_VAT', 'Không chịu thuế', ''}

        tax_text = str(l.get('TaxPercentIDText') or '').strip()

        # 1) Kiểm tra KCT
        if not tax_text or tax_text.upper() in kct_markers:
            return []

        # 2) Parse số % từ text (loại bỏ ký tự %)
        try:
            rate_str = tax_text.replace('%', '').strip()
            rate = float(rate_str)
        except Exception as e:
            _logger.warning("❌ Không parse được VAT '%s': %s -> bỏ qua", tax_text, e)
            return []

        # 3) 0% khác KCT → tạo/gắn VAT 0%
        if abs(rate) < 1e-9:
            tax = self._get_or_create_vn_vat(0.0, use='sale')
            return [tax.id] if tax else []

        # 4) Các mức khác (8%, 10%, v.v.)
        tax = self._get_or_create_vn_vat(rate, use='sale')
        return [tax.id] if tax else []


    def _sync_all_product_names_from_misa(self, product_lines):
        """
        Đồng bộ tên tất cả sản phẩm từ MISA (bao gồm cả combo parent và child).
        Gọi hàm này TRƯỚC khi xử lý các dòng SO để đảm bảo tên luôn đồng bộ.
        """
        odoo_utils = self.env['odoo.utils']
        synced_count = 0
        
        for misa_line in product_lines:
            # Bỏ qua combo child vì chỉ cần sync parent
            if misa_line.get("IsChildProduct"):
                continue
                
            product_code = misa_line.get("ProductIDText")
            product_name = misa_line.get("Description") or product_code
            
            if product_code and product_name:
                result = odoo_utils._sync_product_name_from_misa(product_code, product_name)
                if result:
                    synced_count += 1
        
        if synced_count > 0:
            _logger.info("🔄 Đã đồng bộ tên cho %d sản phẩm từ MISA", synced_count)
        
        return synced_count

    def _update_existing_so_taxes(self, existing_order, product_lines):
        """
        Cập nhật thuế cho SO đã tồn tại.
        So khớp dòng theo ProductIDText và cập nhật tax_id.
        """
        if existing_order.state in ('cancel', 'done'):
            _logger.info("⚠️ SO %s đã ở trạng thái %s, không cập nhật thuế",
                        existing_order.name, existing_order.state)
            return False

        odoo_utils = self.env['odoo.utils']
        updated_count = 0
        
        for misa_line in product_lines:
            product_code = misa_line.get("ProductIDText")
            if not product_code:
                continue

            # ✅ ĐỒNG BỘ TÊN SẢN PHẨM TỪ MISA
            product_name = misa_line.get("Description") or product_code
            odoo_utils._sync_product_name_from_misa(product_code, product_name)

            odoo_line = existing_order.order_line.filtered(
                lambda l: l.product_id.default_code == product_code
            )
            if not odoo_line:
                continue

            tax_ids = self._tax_ids_from_misa_sale_line(misa_line)
            current_tax_ids = set(odoo_line[0].tax_id.ids)
            new_tax_ids = set(tax_ids)

            if current_tax_ids != new_tax_ids:
                try:
                    if tax_ids:
                        odoo_line[0].write({'tax_id': [(6, 0, tax_ids)]})
                    else:
                        # MISA không có thuế → Clear thuế
                        odoo_line[0].write({'tax_id': [(5, 0, 0)]})
                    updated_count += 1
                except Exception as e:
                    _logger.error("❌ Lỗi khi cập nhật thuế cho %s: %s",
                                product_code, e)

        if updated_count > 0:
            existing_order.message_post(
                body=_("Đã cập nhật thuế cho %d dòng hàng khi đồng bộ từ MISA")
                % updated_count
            )
            _logger.info("🎯 Đã cập nhật %d dòng thuế cho SO %s",
                        updated_count, existing_order.name)

        return updated_count > 0

    def _update_existing_combo_products(self, existing_order, grouped_lines, sale_headers):
        """
        Cập nhật combo product cho SO đã tồn tại.
        Nhóm children theo ParentProductID/ParentProductIDText (giống sync hard).
        """
        if existing_order.state in ('cancel', 'done'):
            _logger.info("SO %s đã ở trạng thái %s, bỏ qua cập nhật combo",
                        existing_order.name, existing_order.state)
            return False

        misa_utils = self.env['misa.api.utils']
        odoo_utils = self.env['odoo.utils']
        updated_count = 0

        # ===== NHÓM CHILDREN THEO CHA (HYBRID: Explicit + Smart Matching) =====
        children_by_parent = {}  # {parent_code: [child_data, ...]}
        children_without_parent = []
        
        # Build map: parent_id -> parent_code
        parent_id_to_code = {}
        parent_code_set = set()
        
        # Bước 1: Scan parents
        for line in (grouped_lines or []):
            if line.get("IsSetProduct"):
                parent_code = (line.get("ProductIDText") or "").strip()
                parent_id = line.get("ProductID") or line.get("ProductId")
                if parent_code:
                    parent_code_set.add(parent_code)
                    if parent_id:
                        parent_id_to_code[str(parent_id)] = parent_code
        
        # Bước 2: Scan children - ưu tiên explicit, thu thập children_without_parent
        for ch in (grouped_lines or []):
            if not ch.get("IsChildProduct"):
                continue
            
            child_code = (ch.get("ProductIDText") or "").strip()
            p_id = ch.get("ParentProductID") or ch.get("ParentProductId")
            p_code = (ch.get("ParentProductIDText") or "").strip()
            
            # Xác định parent_code bằng explicit data
            parent_code = None
            if p_code and p_code in parent_code_set:
                parent_code = p_code
            elif p_id and str(p_id) in parent_id_to_code:
                parent_code = parent_id_to_code[str(p_id)]
            
            if parent_code and child_code:
                children_by_parent.setdefault(parent_code, []).append(ch)
                _logger.info("🔗 Wizard: Explicit map child '%s' → parent '%s'", child_code, parent_code)
            else:
                children_without_parent.append(ch)
        
        # Bước 3: Smart matching cho children không có explicit parent
        if children_without_parent:
            _logger.info("🔄 Wizard: Smart matching %s children...", len(children_without_parent))
            current_parent_code = None
            for it in (grouped_lines or []):
                if it.get("IsSetProduct"):
                    current_parent_code = (it.get("ProductIDText") or "").strip()
                elif it.get("IsChildProduct") and current_parent_code:
                    if any(c.get("ProductIDText") == it.get("ProductIDText") for c in children_without_parent):
                        children_by_parent.setdefault(current_parent_code, []).append(it)
                        _logger.info("🔗 Wizard: Smart map child '%s' → parent '%s'", 
                                   it.get("ProductIDText"), current_parent_code)

        # ===== XỬ LÝ TỪNG DÒNG COMBO =====
        for line in grouped_lines:
            # Chỉ xử lý dòng combo cha
            if not line.get("IsSetProduct"):
                continue
                
            product_code = line.get("ProductIDText")
            if not product_code:
                continue
            
            misa_product_id = line.get("ProductID") or line.get("ProductId") or None
            
            # Lấy children TRA TRỰC TIẾP THEO product_code
            children_for_parent = list(children_by_parent.get(product_code, []))

            try:
                # Tạo/cập nhật combo product + ĐỔ Combo Items đúng schema
                combo_product = misa_utils.get_or_create_combo_product(
                    combo_data=line,
                    children_data=children_for_parent,   # có thể rỗng -> util tự fetch bằng headers
                    env=self.env,
                    sale_headers=sale_headers,           # BẮT BUỘC để util gọi API lấy con
                )

                if not combo_product:
                    _logger.warning("⚠️ Không tạo/cập nhật được combo %s", product_code)
                    continue

                # Tìm dòng SO tương ứng theo default_code
                so_line = existing_order.order_line.filtered(
                    lambda l: l.product_id.default_code == product_code
                )

                if so_line:
                    if so_line[0].product_id.id != combo_product.id:
                        try:
                            so_line[0].write({'product_id': combo_product.id})
                            updated_count += 1
                            _logger.info("✅ Cập nhật combo product %s", product_code)
                        except Exception as e:
                            _logger.error("❌ Lỗi cập nhật product_id cho combo %s: %s", product_code, e)
                    else:
                        updated_count += 1
                else:
                    _logger.warning("⚠️ Không tìm thấy dòng SO cho combo %s", product_code)

            except Exception as e:
                _logger.exception("❌ Lỗi xử lý combo %s", product_code)

        if updated_count > 0:
            existing_order.message_post(
                body=_("Đã cập nhật %d combo product khi đồng bộ từ MISA") % updated_count
            )
            _logger.info("🎯 Đã cập nhật %d combo cho SO %s", updated_count, existing_order.name)

        return updated_count > 0
    
    def _add_missing_lines_to_existing_so(self, existing_order, grouped_lines, sale_headers):
        """
        Chỉ TẠO MỚI các dòng còn thiếu trong SO (từ trang 2+ của MISA).
        KHÔNG sửa/cập nhật dòng đã có.        
        Returns: số dòng đã tạo
        """
        if existing_order.state in ('cancel', 'done'):
            _logger.info("⚠️ SO %s ở trạng thái %s, không thêm dòng",
                        existing_order.name, existing_order.state)
            return 0
        
        odoo_utils = self.env['odoo.utils']
        misa_utils = self.env['misa.api.utils']
        
        # Map các dòng hiện có theo product code
        existing_codes = set()
        for line in existing_order.order_line:
            code = (line.product_id.default_code or '').strip()
            if code:
                existing_codes.add(code)
        
        _logger.info("📋 SO %s: Có %d dòng hiện tại, MISA có %d dòng",
                    existing_order.name, len(existing_codes), len(grouped_lines))
        
        created_count = 0
        
        # ===== XỬ LÝ TỪNG DÒNG MISA =====
        for misa_line in grouped_lines:
            product_code = (misa_line.get("ProductIDText") or "").strip()
            if not product_code:
                continue
            
            # Bỏ qua combo child
            if misa_line.get("IsChildProduct"):
                continue
            
            # ===== CHỈ XỬ LÝ DÒNG CHƯA CÓ =====
            if product_code in existing_codes:
                continue  # Dòng đã có → bỏ qua
            
            _logger.info("   ➕ Dòng thiếu: %s", product_code)
            
            # ===== LẤY THÔNG TIN TỪ MISA =====
            description = misa_line.get("Description") or product_code
            qty = float(misa_line.get("Amount", 1) or 0.0)
            price_unit = float(misa_line.get("Price", 0) or 0.0)
            discount_percent = float(misa_line.get("DiscountPercent", 0) or 0.0)
            uom_name = (misa_line.get("UnitIDText") or "Cái").strip()
            note = misa_line.get("DescriptionProduct") or misa_line.get("Note") or ""
            misa_product_id = misa_line.get("ProductID") or misa_line.get("ProductId") or None
            is_combo_parent = misa_line.get("IsSetProduct", False)
            
            # ===== TẠO/LẤY PRODUCT =====
            if is_combo_parent:
                # Combo parent
                combo_product = misa_utils.get_or_create_combo_product(
                    combo_data=misa_line,
                    children_data=[],
                    env=self.env,
                    sale_headers=sale_headers,
                )
                product = combo_product or odoo_utils._get_or_create_product(
                    code=product_code,
                    name=description,
                    unit_name=uom_name,
                    cost=price_unit,
                    product_type="consu",
                    purchase_ok=True,
                    sale_ok=True
                )
            else:
                # Dòng thường
                product = odoo_utils._get_or_create_product(
                    code=product_code,
                    name=description,
                    unit_name=uom_name,
                    cost=price_unit,
                    product_type="consu",
                    purchase_ok=True,
                    sale_ok=True
                )
            
            # ===== QUY ĐỔI UOM =====
            qty_for_odoo, price_for_odoo, use_default_uom = self._convert_qty_price_to_default_uom(
                product=product,
                misa_uom_text=uom_name,
                qty=qty,
                price=price_unit,
                misa_product_id=misa_product_id,
                headers=sale_headers
            )
            
            # ===== CHUẨN BỊ VALS =====
            vals_line = {
                'order_id': existing_order.id,
                'product_id': product.id,
                'name': description,
                'product_uom_qty': qty_for_odoo,
                'price_unit': price_for_odoo,
                'discount': discount_percent,
                'note': note,
            }
            if not use_default_uom and product.uom_id:
                vals_line['product_uom'] = product.uom_id.id
            
            # Thuế
            tax_ids = self._tax_ids_from_misa_sale_line(misa_line)
            if tax_ids:
                vals_line['tax_id'] = [(6, 0, tax_ids)]
            else:
                # MISA không có thuế → Clear thuế
                vals_line['tax_id'] = [(5, 0, 0)]
            
            # ===== TẠO DÒNG MỚI =====
            try:
                self.env['sale.order.line'].create(vals_line)
                created_count += 1
                _logger.info("      ✓ Created: %s (qty=%s, price=%s)", 
                            product_code, qty_for_odoo, price_for_odoo)
            except Exception as e:
                _logger.error("      ❌ Lỗi tạo dòng %s: %s", product_code, e)
        
        # ===== POST MESSAGE =====
        if created_count > 0:
            existing_order.message_post(
                body=_("Đã thêm %d dòng thiếu từ MISA (trang 2+)") % created_count
            )
            _logger.info("🎯 SO %s: Đã thêm %d dòng thiếu", existing_order.name, created_count)
        else:
            _logger.info("   ℹ️ Không có dòng thiếu cần thêm")
        
        return created_count

    # ===== Helpers cho địa chỉ giao hàng =====
    def _vn_country(self):
        return self.env['res.country'].search([('code', '=', 'VN')], limit=1)

    def _vn_state_by_name(self, name):
        """Tìm res.country.state theo tên (ví dụ: 'Đồng Nai', 'Thành phố Hồ Chí Minh')."""
        if not name:
            return False
        country = self._vn_country()
        State = self.env['res.country.state']
        # Thử khớp chính xác
        st = State.search([('name', '=', name), ('country_id', '=', country.id)], limit=1)
        if st:
            return st
        # Thử khớp tương đối (hơi rộng tay cho dữ liệu lệch)
        st = State.search([('name', 'ilike', name), ('country_id', '=', country.id)], limit=1)
        return st or False

    def _get_or_create_delivery_contact(self, parent_partner, addr_str, phone=None, province_text=None, contact_name=None, is_e_account=False):
        """
        Tạo/nhặt contact con dưới parent_partner.
        
        Logic cho e_accounts (is_e_account=True):
          - LUÔN tìm theo địa chỉ (addr_str) trước, vì mỗi đơn là một người mua khác nhau
          - Nếu không tìm thấy địa chỉ khớp → TẠO MỚI liên hệ với địa chỉ đó
          - KHÔNG tìm theo tên để tránh cập nhật liên hệ cũ
          - Dùng type='delivery' để hiển thị icon xe tải
          
        Logic cho khách hàng thường:
          - Nếu có contact_name: Tìm theo (parent_id, name=contact_name)
            -> Nếu thấy: UPDATE theo dữ liệu mới nhất.
            -> Nếu không thấy: TẠO MỚI với name=contact_name
          - Nếu không có contact_name: Tìm theo (parent_id, street=addr_str)
            -> Nếu thấy: UPDATE các field thiếu.
            -> Nếu không thấy: TẠO MỚI với name=parent_partner.name
          - Dùng type='contact' để hiển thị tên contact thay vì tên công ty cha
        """
        Partner = self.env['res.partner']
        country = self._vn_country()
        state = self._vn_state_by_name(province_text) if province_text else False

        existing = None
        
        # ===== LOGIC ĐẶC BIỆT CHO E_ACCOUNTS =====
        # Với e_accounts, mỗi đơn là một người mua khác nhau, nên LUÔN tìm theo địa chỉ
        if is_e_account:
            if addr_str:
                _logger.info("🔎 [E-ACCOUNT] Search delivery by ADDR: '%s' (parent=%s)", addr_str, parent_partner.id)
                existing = Partner.search([
                    ('parent_id', '=', parent_partner.id),
                    ('type', 'in', ['delivery', 'contact']),
                    ('street', '=', addr_str),
                ], limit=1)
        else:
            # ===== LOGIC CHO KHÁCH HÀNG THƯỜNG =====
            if contact_name:
                 # Ưu tiên tìm theo tên contact
                 # BỎ CHECK ADDR_STR để cho phép cập nhật địa chỉ khi tên trùng
                 domain = [
                    ('parent_id', '=', parent_partner.id),
                    ('type', 'in', ['delivery', 'contact']),
                    ('name', '=', contact_name)
                 ]
                 
                 _logger.info("🔎 Search delivery by NAME: '%s' (parent=%s)", contact_name, parent_partner.id)
                 existing = Partner.search(domain, limit=1)

            elif addr_str:
                 # Chỉ tìm theo địa chỉ nếu KHÔNG có contact_name
                 _logger.info("🔎 Search delivery by ADDR: '%s' (parent=%s)", addr_str, parent_partner.id)
                 existing = Partner.search([
                    ('parent_id', '=', parent_partner.id),
                    ('type', 'in', ['delivery', 'contact']),
                    ('street', '=', addr_str),
                 ], limit=1)
        
        if existing:
            _logger.info("✅ Found existing delivery contact: %s (id=%s)", existing.name, existing.id)

        if existing:
            # Cập nhật thông tin (Force update để đảm bảo đồng bộ)
            vals_upd = {}

            # Luôn cập nhật tên nếu có contact_name và khác tên hiện tại
            if contact_name and existing.name != contact_name:
                vals_upd['name'] = contact_name

            # CẬP NHẬT ĐỊA CHỈ MỚI (nếu có)
            if addr_str and existing.street != addr_str:
                vals_upd['street'] = addr_str

            if country and existing.country_id != country:
                vals_upd['country_id'] = country.id
            if state and existing.state_id != state:
                vals_upd['state_id'] = state.id
            if province_text and existing.city != province_text:
                vals_upd['city'] = province_text
            if phone and existing.phone != phone:
                vals_upd['phone'] = phone

            if vals_upd:
                _logger.info("♻️ Updating delivery contact %s: %s", existing.name, vals_upd)
                existing.write(vals_upd)
            else:
                _logger.info("♻️ Existing delivery contact %s found, NO CHANGES detected.", existing.name)
            return existing

        # Tạo mới contact
        # Với e_accounts: dùng type='delivery' để hiển thị icon xe tải
        # Với khách thường: dùng type='delivery' luôn để đảm bảo nó là địa chỉ giao hàng
        contact_type = 'delivery'
        vals = {
            'name': contact_name or parent_partner.name,
            'type': contact_type,
            'parent_id': parent_partner.id,
            'street': addr_str or '',
            'city': province_text or False,
            'phone': phone or False,
            'country_id': country.id if country else False,
            'state_id': state.id if state else False,
        }
        _logger.info("🆕 Creating new delivery contact (type=%s) with vals: %s", contact_type, vals)
        return Partner.create(vals)

    def action_import_from_api(self):
        odoo_utils = self.env['odoo.utils']
        misa_utils = self.env['misa.api.utils']
        misa_config = self.env['misa.config']

        crm_token = misa_utils._fetch_login_crm_token()

        token_url = "https://crmconnect.misa.vn/api/v2/Account"
        orders_url = "https://amisapp.misa.vn/crm/g2/api/business/SaleOrder/Grid"
        order_detail_url = "https://amisapp.misa.vn/crm/g2/api/business/SaleOrder/DataSubPaging"

        sale_headers = misa_config.get_crm_header(crm_token)


        start_datetime = datetime.combine(self.from_date, datetime.min.time())
        end_datetime = datetime.combine(self.to_date, datetime.max.time())

        stock_mapping = {
            "HCM": "TSN/Stock",
            "BENCAM": "KBC/Tồn kho",
            "HIENDUC": "KHD/Tồn kho",
            "HCM_SHOWROOM": "TSNSR/Stock",
            "HLV":"TSN/Stock",
            "BẾN CAM": "KBC/Tồn kho",
            "BẾNCAM": "KBC/Tồn kho",
            "HIỀN ĐỨC": "KHD/Tồn kho",
            "ĐÀ NẴNG": "KDN/Tồn kho",
            "ĐÀNẴNG": "KDN/Tồn kho",
            "HIỀNĐỨC": "KHD/Tồn kho",
            "HIENDUC": "KHD/Tồn kho",
            "DANANG": "KDN/Tồn kho",
        }

        e_accounts = {
            "TIKTOK HOÀNG LONG VŨ",
            # "SHOPEE TRANG MILWAUKEE",
            # "SHOPEE TRANG TBCN HLV",
            # "SHOPEE TRANG DEWALT STANLEY",
            # "KHÁCH LẺ KHÔNG LẤY HÓA ĐƠN_SHOPEE STANLEY",
            # "KHÁCH LẺ KHÔNG LẤY HÓA ĐƠN_SHOPEE",
            # "KHÁCH LẺ KHÔNG LẤY HÓA ĐƠN_SHOPEE TBCN",
            "KHÁCH LẺ KHÔNG LẤY HÓA ĐƠN_TIKTOK",
            # "KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE",
            # "KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE TBCN",
            # "KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE STANLEY",
            "KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_TIKTOK",
            # "KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE HLV",
            "TOOL DEWALT",
            # "KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE STANLEY",
            # "KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE MILWAUKEE",
            # "KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE DEWALT",
        }

    
        def line_subtotal(l):
            qty = float(l.get("Amount", 1) or 0.0)
            price = float(l.get("Price", 0) or 0.0)
            disc = float(l.get("DiscountPercent", 0) or 0.0)
            return qty * price * (1.0 - disc / 100.0)

        page = 1
        while True:
            payload = misa_config.get_crm_sale_order_payload(start_datetime, end_datetime, page)
            try:
                response = requests.post(orders_url, headers=sale_headers, json=payload)
                response.raise_for_status()
                orders = response.json().get("Data", [])
            except Exception as e:
                raise Exception(f"Lỗi khi lấy đơn hàng từ API MISA: {e} {payload}")

            for order in orders:
                # --- Filter theo account & trạng thái ---
                customer_name = order.get("AccountIDText") 
                origin = order.get("SaleOrderName")
                status = (order.get("RevenueStatusIDText") or "").strip().lower()
                status_id = order.get("RevenueStatusID")
                revenue_status_id = order.get("RevenueStatusID")
                order_ref = order.get("SaleOrderNo")
                order_id = order.get("ID")
                account_id = order.get("AccountID") or order.get("AccountId")
                zns = bool(order.get("CustomField23", False))

                # Bỏ qua đơn đã giao (DeliveryStatusID=2)
                delivery_status = order.get("DeliveryStatusID", "0")
                if delivery_status is not None and str(delivery_status).strip() == "2":
                    _logger.info("⏭️ Bỏ qua SO %s (id=%s) vì Đơn hàng đã giao (DeliveryStatusID=2)", order.get("SaleOrderNo"), order.get("ID"))
                    continue
                
                # Nếu là 'Từ chối ghi' → hủy các SO hiện có trùng tên rồi bỏ qua import
                if revenue_status_id == 4 or status == "từ chối ghi":
                    # found = self.env['sale.order'].sudo().search([('name', '=', order_ref)])
                    # if found:
                    #     for so in found:
                    #         self._force_cancel_sale_order(so, revenue_status_id, status)
                    continue
                



                # Bỏ qua SO 'Bản nháp' mà không thuộc e_accounts
                #if customer_name not in e_accounts and status == "Bản nháp" :
                if customer_name not in e_accounts and (status in ["Bản nháp", "bản nháp"] or status_id == 1):
                    _logger.info("⏭️ SO %s là 'Bản nháp' và không thuộc e_accounts => bỏ qua", order.get("SaleOrderNo"))
                    continue

                # --- Lấy chi tiết dòng hàng ---
                order_id = order.get("ID")
                misa_id_str = str(order_id) if order_id else False  
                payload_detail = misa_config.get_crm_sale_order_detail_payload(order_id)
                
                if customer_name not in e_accounts :
                    continue
                if customer_name in e_accounts and not order.get('DeliveryOrderNumber'):
                    continue

                # base_pick_name logic has been moved down
                # if customer_name in e_accounts:
                #     base_pick_name = order.get('DeliveryOrderNumber')
                # else:
                #     base_pick_name = order.get('SaleOrderNo')
                product_lines = misa_utils.get_list_product_by_order_crm(order_detail_url, sale_headers, payload_detail)
                

                shipping_address_str = misa_utils.get_shipping_address(
                    sale_order_id=order_id,
                    order_ref=order.get("SaleOrderNo"),
                    token=crm_token
                )
                # NEW: fetch OwnerIDText, SaleOrderDate, OtherSysOrderCode, DeliveryOrderNumber from FormDataNew
                owner_date = {}
                try:
                    owner_date = misa_utils.get_saleorder_owner_and_date(order_id, sale_headers) or {}
                except Exception as _e:
                    _logger.warning("Không lấy được thông tin từ FormDataNew cho SO=%s: %s", order_id, _e)

                # Ưu tiên lấy OtherSysOrderCode từ FormDataNew, fallback về DeliveryOrderNumber từ FormDataNew, rồi mới tới Grid
                sys_code = owner_date.get('other_sys_order_code') or order.get('OtherSysOrderCode')
                del_code = owner_date.get('delivery_order_number') or order.get('DeliveryOrderNumber')
                
                if del_code and str(del_code).startswith("VN"):
                    pick_code = sys_code
                else:
                    pick_code = del_code

                if customer_name in e_accounts and not pick_code:
                    continue

                if customer_name in e_accounts:
                    base_pick_name = pick_code
                else:
                    base_pick_name = order.get('SaleOrderNo')
                # tỉnh/thành để map state/city
                province_text = (
                    order.get("ShippingProvinceIDCustomText")
                    or order.get("ShippingProvinceIDText")
                    or order.get("BillingProvinceIDCustomText")
                    or order.get("BillingProvinceIDText")
                )
                phone_text = order.get("Phone")

                

                # === MAPPING COMBO CHILD ===
                def _expand_combo_lines(lines: list[dict]) -> list[dict]:
                    """
                    Trước đây: chuyển combo cha → thêm các dòng con vào danh sách.
                    Nay: để giống hard sync, KHÔNG thêm các dòng con vào SO.
                    Vẫn có thể log phân tích/khóa nhóm để dùng đoạn sau, nhưng trả về nguyên list.
                    """
                    try:
                        n_set = sum(1 for it in (lines or []) if it.get("IsSetProduct"))
                        n_child = sum(1 for it in (lines or []) if it.get("IsChildProduct"))
                        _logger.info("ℹ️ _expand_combo_lines: found %d combo-parent, %d child (child sẽ không expand vào SO).", n_set, n_child)
                    except Exception:
                        pass
                    return lines or []
                
                product_lines = _expand_combo_lines(product_lines)
                
                # --- Gom dòng theo kho (bao gồm cả combo children) ---
                lines_by_stock = defaultdict(list)
                current_stock_id = None  # Track kho hiện tại để gán cho combo children
                
                for l in product_lines:
                    sid = l.get("StockIDText")
                    is_combo_parent = l.get("IsSetProduct")
                    is_combo_child = l.get("IsChildProduct")
                    
                    if sid:
                        # Dòng có StockIDText (combo cha hoặc dòng thường)
                        current_stock_id = sid
                        lines_by_stock[sid].append(l)
                    elif is_combo_parent and not sid:
                        # 🆕 COMBO CHA không có StockIDText (hoặc rỗng)
                        # → Sẽ lấy kho từ DÒNG CON ĐẦU TIÊN
                        # Tạm thời KHÔNG thêm vào lines_by_stock, chờ xử lý sau
                        _logger.info("🔍 Combo parent '%s' không có StockIDText, sẽ lấy từ children", 
                                    l.get("ProductIDText"))
                        # Tìm dòng con đầu tiên để lấy kho
                        next_child_stock = None
                        for next_l in product_lines[product_lines.index(l)+1:]:
                            if next_l.get("IsChildProduct"):
                                next_child_stock = next_l.get("StockIDText")
                                if next_child_stock:
                                    break
                        
                        if next_child_stock:
                            _logger.info("  ├─ Gán combo parent '%s' vào kho '%s' (từ child)", 
                                        l.get("ProductIDText"), next_child_stock)
                            current_stock_id = next_child_stock
                            lines_by_stock[next_child_stock].append(l)
                        else:
                            _logger.warning("⚠️ Combo parent '%s' không tìm thấy kho từ children!", 
                                          l.get("ProductIDText"))
                    elif is_combo_child and current_stock_id:
                        # Dòng combo con: gán vào kho của dòng cha (trước đó)
                        lines_by_stock[current_stock_id].append(l)
                        _logger.debug("🔗 Gán combo child '%s' vào kho '%s'", 
                                     l.get("ProductIDText"), current_stock_id)
                    elif sid is None and not is_combo_child:
                        # Dòng không có kho và không phải combo con → bỏ qua
                        _logger.warning("⚠️ Dòng '%s' không có StockIDText và không phải combo child", 
                                       l.get("ProductIDText"))

                if not lines_by_stock:
                    _logger.warning("⛔ Không có dòng hàng hợp lệ theo kho cho SO %s", order.get("SaleOrderNo"))
                    continue

                order_ref_base = order.get("SaleOrderNo")
                order_date = parse(order.get("SaleOrderDate")).replace(tzinfo=None)
                
                deadline_date_raw = order.get("DeadlineDate")
                commitment_date = False
                if deadline_date_raw:
                    try:
                        # Parse và bỏ timezone để lưu vào Odoo (Odoo lưu UTC naive hoặc theo context server)
                        commitment_date = parse(deadline_date_raw).replace(tzinfo=None)
                    except Exception:
                        commitment_date = False
                        
                        
                        
                if not order_ref_base or not customer_name:
                    _logger.warning("⛔ Thiếu mã đơn hoặc tên khách hàng trong đơn hàng: %s", order)
                    continue

                # Ưu tiên lấy tên người nhận hàng từ ShippingContactIDText, nếu không có thì dùng AccountIDText
                # partner_name_for_so = owner_date.get('shipping_contact') or customer_name
       
                # --- NEW LOGIC: Sync from MISA Account API first ---
                partner = None
                ident = {}
                if account_id:
                    partner = misa_utils._sync_customer_from_misa_account_api(account_id, sale_headers)
                    # Lấy identity sớm để dùng cho fallback (tránh gọi 2 lần)
                    try:
                        ident = misa_utils.get_account_identity(account_id, sale_headers) or {}
                    except Exception as _e:
                        _logger.warning("Không lấy được account identity cho AccountID=%s: %s", account_id, _e)

                if not partner:
                    # Fallback tìm theo tên:
                    # - Nếu tên trùng nhưng mã CRM khác → tạo mới (tránh ghi đè liên hệ của KH khác)
                    # - Nếu chưa có mã → dùng liên hệ cũ như bình thường
                    misa_code_preview = ident.get("account_number") or ident.get("id")
                    partner_name_for_so = customer_name
                    partner = odoo_utils._get_or_create_partner(
                        partner_name_for_so,
                        misa_code=misa_code_preview,
                        tax_code=ident.get("taxcode"),
                    )

                try:
                    if account_id and ident:
                        commercial = partner.commercial_partner_id or partner
                        # VAT là thông tin công ty → ghi lên cha
                        if ident.get("taxcode") and not commercial.vat:
                            commercial.write({"vat": ident["taxcode"]})
                            commercial.message_post(body=f"Cập nhật từ MISA: VAT=<b>{ident['taxcode']}</b>")
                    else:
                        _logger.info("Không có AccountID trong đơn, bỏ qua cập nhật đối tác.")
                except Exception as e:
                    _logger.warning("Không thể cập nhật VAT đối tác từ MISA (AccountID=%s): %s", account_id, e)

                # ===== TẠO/GÁN ĐỊA CHỈ GIAO HÀNG (contact delivery) =====
                _logger.info("📍 [%s] Tạo delivery contact với addr_str='%s', is_e_account=%s", 
                            order_ref_base, 
                            shipping_address_str or order.get("ShippingAddress") or order.get("BillingAddress"),
                            customer_name in e_accounts)
                delivery_contact = self._get_or_create_delivery_contact(
                    parent_partner=partner,
                    addr_str=shipping_address_str or order.get("ShippingAddress") or order.get("BillingAddress") or order_ref_base,
                    phone=phone_text,
                    province_text=province_text,
                    contact_name=owner_date.get('shipping_contact'),
                    is_e_account=(customer_name in e_accounts)
                )
                _logger.info("📍 [%s] Delivery contact created/found: id=%s, name='%s', street='%s'",
                            order_ref_base, delivery_contact.id, delivery_contact.name, delivery_contact.street)

                distinct_stocks = [s for s in lines_by_stock.keys() if s in stock_mapping]
                if not distinct_stocks:
                    _logger.warning("📛 Tất cả kho của đơn %s không nằm trong mapping -> bỏ qua", order_ref_base)
                    continue

                # ========== CASE 1: CHỈ 1 KHO -> GIỮ NGUYÊN TÊN SO ==========
                if len(distinct_stocks) == 1:
                    stock_id = distinct_stocks[0]
                    grouped_lines = lines_by_stock[stock_id]

                    # tìm location/warehouse
                    location_name = stock_mapping[stock_id]
                    location = self.env['stock.location'].search([
                        ('complete_name', '=', location_name)
                    ], limit=1)
                    if not location:
                        _logger.warning("❌ Không tìm thấy stock.location cho kho %s (%s)", stock_id, location_name)
                        continue

                    warehouse = self.env['stock.warehouse'].search([
                        ('view_location_id', '=', location.location_id.id)
                    ], limit=1)
                    if not warehouse:
                        _logger.warning("🚫 Không tìm thấy warehouse cho kho: %s", stock_id)
                        continue

                    order_ref = order_ref_base  # giữ nguyên
                    # Kiểm tra SO đã tồn tại
                    existing_order = self.env['sale.order'].search([('name', '=', order_ref)], limit=1)
                    if existing_order:
                        # if misa_id_str and not existing_order.misa_id:
                        #     existing_order.misa_id = misa_id_str
                        # # >>> ĐỒNG BỘ TÊN SẢN PHẨM TỪ MISA (TRƯỚC KHI XỬ LÝ) <<<
                        # self._sync_all_product_names_from_misa(grouped_lines)
                        # # >>> CẬP NHẬT THUẾ CHO SO ĐÃ TỒN TẠI <<<
                        # self._update_existing_so_taxes(existing_order, grouped_lines)
                        # # >>> CẬP NHẬT COMBO PRODUCT (chỉ dòng cha) <<<
                        # self._update_existing_combo_products(existing_order, grouped_lines, sale_headers)
                        # # >>> TẠO MỚI CÁC DÒNG THIẾU (trang 2+) <<<
                        # self._add_missing_lines_to_existing_so(existing_order, grouped_lines, sale_headers)
                        # # Update MISA fields (owner code and order date)
                        # upd = {}
                        # if owner_date.get('owner_code'):
                        #     upd['x_studio_misa_saler_code'] = owner_date['owner_code']
                        # if owner_date.get('sale_order_date'):
                        #     upd['x_studio_misa_order_date'] = owner_date['sale_order_date']
                        # if upd:
                        #     existing_order.write(upd)

                        # # (giữ nguyên các xử lý khác; KHÔNG thêm dòng con)
                        # _logger.info("🔁 SO đã tồn tại: %s, đã cập nhật combo (parent-only)/thuế", order_ref)
                        continue

                    group_total = sum(line_subtotal(l) for l in grouped_lines)
                    sale_vals = {
                        'name': order_ref,
                        'partner_id': delivery_contact.id,  # Cách B: delivery contact làm KH chính
                        'date_order': order_date,
                        'amount_total': group_total,
                        'commitment_date': commitment_date,
                        'partner_shipping_id': delivery_contact.id,
                        'partner_invoice_id': delivery_contact.id,
                        'origin':origin,
                        'warehouse_id': warehouse.id,
                        'misa_id': misa_id_str, 
                        'x_studio_zns': zns,
                        'x_studio_sdt_giao_hang': phone_text or False
                    }
                    # If we have owner code/date, set the Studio fields
                    if owner_date.get('owner_code'):
                        sale_vals['x_studio_misa_saler_code'] = owner_date['owner_code']
                    if owner_date.get('sale_order_date'):
                        sale_vals['x_studio_misa_order_date'] = owner_date['sale_order_date']
                    if owner_date.get('misa_delivery'):
                        sale_vals['x_studio_misa_delivery'] = owner_date['misa_delivery']
                    if owner_date.get('httt'):
                        sale_vals['x_studio_httt'] = owner_date['httt']
                    if owner_date.get('htgh'):
                        sale_vals['x_studio_htgh'] = owner_date['htgh']
                    if owner_date.get('misa_note') and 'x_studio_misa_note' in self.env['sale.order']._fields:
                        sale_vals['x_studio_misa_note'] = owner_date['misa_note']

                    sale_order = self.env['sale.order'].create(sale_vals)
                    _logger.info("✅ [%s] Created SO id=%s with partner_shipping_id=%s (delivery_contact.id=%s)",
                                order_ref, sale_order.id, sale_order.partner_shipping_id.id, delivery_contact.id)
                    
                    # ===== BUILD MAP: COMBO CHILD -> PARENT CODE (HYBRID) =====
                    combo_parent_map = {}  # {misa_line_id: parent_code} - DÙNG LINE ID
                    children_by_parent = {}  # {parent_code: [child_data, ...]}
                    children_without_parent = []
                    
                    # Build map: parent_id -> parent_code
                    parent_id_to_code = {}
                    parent_code_set = set()
                    
                    _logger.info("📦 Wizard: Bắt đầu build combo map từ %d dòng", len(grouped_lines))
                    
                    # Bước 1: Scan parents
                    for line in (grouped_lines or []):
                        if line.get("IsSetProduct"):
                            parent_code = (line.get("ProductIDText") or "").strip()
                            parent_id = line.get("ProductID") or line.get("ProductId")
                            if parent_code:
                                parent_code_set.add(parent_code)
                                if parent_id:
                                    parent_id_to_code[str(parent_id)] = parent_code
                    
                    # Bước 2: Scan children - ưu tiên explicit, thu thập children_without_parent
                    for ch in (grouped_lines or []):
                        if not ch.get("IsChildProduct"):
                            continue
                        
                        child_code = (ch.get("ProductIDText") or "").strip()
                        child_misa_id = ch.get("ID")  # MISA line ID (unique)
                        p_id = ch.get("ParentProductID") or ch.get("ParentProductId")
                        p_code = (ch.get("ParentProductIDText") or "").strip()
                        
                        _logger.info("  🔹 Child: '%s' (ID=%s) | ParentID=%s | ParentCode='%s'", 
                                   child_code, child_misa_id, p_id, p_code)
                        
                        # Xác định parent_code bằng explicit data
                        parent_code = None
                        if p_code and p_code in parent_code_set:
                            parent_code = p_code
                            _logger.info("     ✅ Explicit: ParentProductIDText='%s'", parent_code)
                        elif p_id and str(p_id) in parent_id_to_code:
                            parent_code = parent_id_to_code[str(p_id)]
                            _logger.info("     ✅ Explicit: ParentProductID=%s → '%s'", p_id, parent_code)
                        
                        # Lưu mapping hoặc đưa vào danh sách cần smart matching
                        if child_misa_id and parent_code:
                            combo_parent_map[child_misa_id] = parent_code  # KEY = MISA LINE ID
                            children_by_parent.setdefault(parent_code, []).append(ch)
                            _logger.info("     🔗 Explicit map: ID=%s ('%s') → '%s'", child_misa_id, child_code, parent_code)
                        else:
                            children_without_parent.append(ch)
                            _logger.info("     ⏳ Child '%s' (ID=%s) cần smart matching", child_code, child_misa_id)
                    
                    # Bước 3: Smart matching cho children không có explicit parent
                    if children_without_parent:
                        _logger.info("🔄 Wizard: Smart matching %d children...", len(children_without_parent))
                        matched_child_ids = set()
                        current_parent_code = None
                        for it in (grouped_lines or []):
                            if it.get("IsSetProduct"):
                                current_parent_code = (it.get("ProductIDText") or "").strip()
                            elif it.get("IsChildProduct") and current_parent_code:
                                child_misa_id = it.get("ID")
                                is_in_list = any(c.get("ID") == child_misa_id for c in children_without_parent)
                                if is_in_list and child_misa_id not in matched_child_ids:
                                    child_code = (it.get("ProductIDText") or "").strip()
                                    combo_parent_map[child_misa_id] = current_parent_code  # KEY = MISA LINE ID
                                    children_by_parent.setdefault(current_parent_code, []).append(it)
                                    matched_child_ids.add(child_misa_id)
                                    _logger.info("     🔗 Smart map: ID=%s ('%s') → '%s'", child_misa_id, child_code, current_parent_code)
                    
                    _logger.info("🔍 Wizard: Combo map cuối cùng: %s", combo_parent_map)
                    
                    # ===== XỬ LÝ TỪNG DÒNG MISA (bao gồm CẢ CHA VÀ CON) =====
                    for line in grouped_lines:
                        product_code = line.get("ProductIDText")
                        if not product_code:
                            continue
                        
                        description = line.get("Description") or product_code
                        qty = float(line.get("Amount", 1) or 0.0)
                        price_unit = float(line.get("Price", 0) or 0.0)
                        discount_percent = float(line.get("DiscountPercent", 0) or 0.0)
                        uom_name = (line.get("UnitIDText") or "Cái").strip()
                        note = line.get("DescriptionProduct") or ""
                        misa_product_id = line.get("ProductID") or line.get("ProductId") or None
                        
                        # Xác định xem dòng này là gì
                        is_combo_parent = line.get("IsSetProduct", False)
                        is_combo_child = line.get("IsChildProduct", False)
                        
                        # ===== TẠO/LẤY PRODUCT =====
                        if is_combo_parent:
                            # COMBO CHA: tạo combo product
                            combo_product = misa_utils.get_or_create_combo_product(
                                combo_data=line,
                                children_data=[],  # util tự fetch children nếu cần
                                env=self.env,
                                sale_headers=sale_headers,
                            )
                            product = combo_product or odoo_utils._get_or_create_product(
                                code=product_code,
                                name=description,
                                unit_name=uom_name,
                                cost=price_unit,
                                product_type="consu",
                                purchase_ok=True,
                                sale_ok=True
                            )
                        elif is_combo_child:
                            # COMBO CON: Bỏ qua không tạo dòng SO (đã có BoM Kit ở parent)
                            _logger.info("ℹ️ Skip combo child line: %s", product_code)
                            continue
                        else:
                            # DÒNG THƯỜNG: tạo/cập nhật product với đầy đủ thông tin
                            product = odoo_utils._get_or_create_product(
                                code=product_code,
                                name=description,
                                unit_name=uom_name,
                                cost=price_unit,  # Dòng thường có giá đầy đủ
                                product_type="consu",
                                purchase_ok=True,
                                sale_ok=True
                            )
                        
                        # ===== QUY ĐỔI UOM =====
                        qty_for_odoo, price_for_odoo, use_default_uom = self._convert_qty_price_to_default_uom(
                            product=product,
                            misa_uom_text=uom_name,
                            qty=qty,
                            price=price_unit,
                            misa_product_id=misa_product_id,
                            headers=sale_headers
                        )
                        
                        # ===== TẠO SALE ORDER LINE =====
                        vals_line = {
                            'order_id': sale_order.id,
                            'product_id': product.id,
                            'name': description,
                            'product_uom_qty': qty_for_odoo,
                            'price_unit': price_for_odoo,
                            'discount': discount_percent,
                            'note': note,
                        }
                        if not use_default_uom and product.uom_id:
                            vals_line['product_uom'] = product.uom_id.id
                        
                        # Thuế
                        tax_ids = self._tax_ids_from_misa_sale_line(line)
                        if tax_ids:
                            vals_line['tax_id'] = [(6, 0, tax_ids)]
                        else:
                            # MISA không có thuế (null) → Clear thuế trong Odoo (không dùng default)
                            vals_line['tax_id'] = [(5, 0, 0)]  # Unlink all taxes
                        
                        # Studio fields (Cleaned up)
                        vals_line['x_studio_is_combo_child'] = False
                        vals_line['x_studio_combo_parent_code'] = False
                        
                        # ===== PRODUCTION STATUS FROM MISA =====
                        production_status_text = line.get("CustomField4") or ""
                        if production_status_text:
                            vals_line['x_studio_product_status'] = production_status_text
                        
                        allowed_fields = {'order_id','product_id','name','product_uom_qty','price_unit','discount','note','product_uom','tax_id','x_studio_is_combo_child','x_studio_combo_parent_code','x_studio_product_status'}
                        safe_vals_line = {k: v for k, v in vals_line.items() if k in allowed_fields}
                        self.env['sale.order.line'].create(safe_vals_line)

                    # Confirm để tạo picking
                    # Invalidate ORM cache để mrp thấy được phantom BOM vừa tạo trong cùng transaction
                    self.env.flush_all()
                    self.env.invalidate_all()
                    sale_order.action_confirm()

                    # Đặt tên picking giữ nguyên logic cũ
                    pickings = sale_order.picking_ids
                    if pickings:
                        picking = pickings[0]
                        desired = base_pick_name
                        if not desired:
                            desired = order_ref_base
                        exists = self.env['stock.picking'].search([('name', '=', desired)], limit=1)
                        if exists:
                            _logger.warning("⚠️ Mã phiếu pick %s đã tồn tại, NEXT tạo mã mới: %s", desired, f"{desired}_{picking.id}")
                            # picking.name = f"{desired}_{picking.id}"
                        else:
                            picking.name = desired
                        _logger.info("📦 Đã gán mã phiếu pick: %s cho SO %s", picking.name, order_ref)

                # ========== CASE 2: NHIỀU KHO -> TÁCH NHIỀU SO, THÊM HẬU TỐ ==========
                else:
                    # Build combo map cho toàn bộ product_lines (HYBRID)
                    combo_parent_map_global = {}  # {misa_line_id: parent_code}
                    children_by_parent_global = {}
                    children_without_parent_global = []
                    
                    # Build map: parent_id -> parent_code
                    parent_id_to_code_global = {}
                    parent_code_set_global = set()
                    
                    # Bước 1: Scan parents
                    for line in (product_lines or []):
                        if line.get("IsSetProduct"):
                            parent_code = (line.get("ProductIDText") or "").strip()
                            parent_id = line.get("ProductID") or line.get("ProductId")
                            if parent_code:
                                parent_code_set_global.add(parent_code)
                                if parent_id:
                                    parent_id_to_code_global[str(parent_id)] = parent_code
                    
                    # Bước 2: Scan children - ưu tiên explicit, thu thập children_without_parent
                    for ch in (product_lines or []):
                        if not ch.get("IsChildProduct"):
                            continue
                        
                        child_code = (ch.get("ProductIDText") or "").strip()
                        child_misa_id = ch.get("ID")
                        p_id = ch.get("ParentProductID") or ch.get("ParentProductId")
                        p_code = (ch.get("ParentProductIDText") or "").strip()
                        
                        # Xác định parent_code bằng explicit data
                        parent_code = None
                        if p_code and p_code in parent_code_set_global:
                            parent_code = p_code
                        elif p_id and str(p_id) in parent_id_to_code_global:
                            parent_code = parent_id_to_code_global[str(p_id)]
                        
                        # Lưu mapping hoặc đưa vào danh sách cần smart matching
                        if child_misa_id and parent_code:
                            combo_parent_map_global[child_misa_id] = parent_code  # KEY = MISA LINE ID
                            children_by_parent_global.setdefault(parent_code, []).append(ch)
                        else:
                            children_without_parent_global.append(ch)
                    
                    # Bước 3: Smart matching cho children không có explicit parent
                    if children_without_parent_global:
                        _logger.info("🔄 Multi-warehouse: Smart matching %d children...", len(children_without_parent_global))
                        matched_child_ids = set()
                        current_parent_code = None
                        for it in (product_lines or []):
                            if it.get("IsSetProduct"):
                                current_parent_code = (it.get("ProductIDText") or "").strip()
                            elif it.get("IsChildProduct") and current_parent_code:
                                child_misa_id = it.get("ID")
                                is_in_list = any(c.get("ID") == child_misa_id for c in children_without_parent_global)
                                if is_in_list and child_misa_id not in matched_child_ids:
                                    combo_parent_map_global[child_misa_id] = current_parent_code  # KEY = MISA LINE ID
                                    children_by_parent_global.setdefault(current_parent_code, []).append(it)
                                    matched_child_ids.add(child_misa_id)
                    
                    for stock_id in distinct_stocks:
                        grouped_lines = lines_by_stock[stock_id]

                        location_name = stock_mapping[stock_id]
                        location = self.env['stock.location'].search([
                            ('complete_name', '=', location_name)
                        ], limit=1)
                        if not location:
                            _logger.warning("❌ Không tìm thấy stock.location cho kho %s (%s)", stock_id, location_name)
                            continue

                        warehouse = self.env['stock.warehouse'].search([
                            ('view_location_id', '=', location.location_id.id)
                        ], limit=1)
                        if not warehouse:
                            _logger.warning("🚫 Không tìm thấy warehouse cho kho: %s", stock_id)
                            continue

                        order_ref = f"{order_ref_base}-{stock_id}"

                        # Kiểm tra SO đã tồn tại
                        existing_order = self.env['sale.order'].search([('name', '=', order_ref)], limit=1)
                        if existing_order:
                            if misa_id_str and not existing_order.misa_id:
                                existing_order.misa_id = misa_id_str
                            # >>> ĐỒNG BỘ TÊN SẢN PHẨM TỪ MISA (TRƯỚC KHI XỬ LÝ) <<<
                            self._sync_all_product_names_from_misa(grouped_lines)
                            # >>> CẬP NHẬT THUẾ CHO SO ĐÃ TỒN TẠI <<<
                            self._update_existing_so_taxes(existing_order, grouped_lines)
                            # >>> THÊM: CẬP NHẬT COMBO PRODUCT (parent-only) <<<
                            self._update_existing_combo_products(existing_order, grouped_lines, sale_headers)
                            # >>> TẠO MỚI CÁC DÒNG THIẾU (trang 2+) <<<
                            self._add_missing_lines_to_existing_so(existing_order, grouped_lines, sale_headers)
                            upd = {}
                            if owner_date.get('owner_code'):
                                upd['x_studio_misa_saler_code'] = owner_date['owner_code']
                            if owner_date.get('sale_order_date'):
                                upd['x_studio_misa_order_date'] = owner_date['sale_order_date']
                            if owner_date.get('misa_delivery'):
                                upd['x_studio_misa_delivery'] = owner_date['misa_delivery']
                            if owner_date.get('misa_note') and 'x_studio_misa_note' in self.env['sale.order']._fields:
                                upd['x_studio_misa_note'] = owner_date['misa_note']
                            if commitment_date:
                                upd['commitment_date'] = commitment_date
                            if upd:
                                existing_order.write(upd)
                            _logger.info("🔁 SO đã tồn tại: %s, đã cập nhật thuế", order_ref)
                            continue

                        group_total = sum(line_subtotal(l) for l in grouped_lines)
                        sale_vals = {
                            'name': order_ref,
                            'partner_id': delivery_contact.id,  # Cách B: delivery contact làm KH chính
                            'date_order': order_date,
                            'partner_shipping_id': delivery_contact.id,
                            'partner_invoice_id': delivery_contact.id,
                            'commitment_date': commitment_date,
                            'amount_total': group_total,       # có thể để Odoo tự tính lại sau khi tạo line
                            'warehouse_id': warehouse.id,
                            'origin': origin,
                            'misa_id': misa_id_str,
                        }
                        if owner_date.get('owner_code'):
                            sale_vals['x_studio_misa_saler_code'] = owner_date['owner_code']
                        if owner_date.get('sale_order_date'):
                            sale_vals['x_studio_misa_order_date'] = owner_date['sale_order_date']
                        if owner_date.get('misa_delivery'):
                            sale_vals['x_studio_misa_delivery'] = owner_date['misa_delivery']
                        if owner_date.get('misa_note') and 'x_studio_misa_note' in self.env['sale.order']._fields:
                            sale_vals['x_studio_misa_note'] = owner_date['misa_note']

                        sale_order = self.env['sale.order'].create(sale_vals)

                        # ===== XỬ LÝ TỪNG DÒNG MISA (bao gồm CẢ CHA VÀ CON) =====
                        for line in grouped_lines:
                            product_code = line.get("ProductIDText")
                            if not product_code:
                                continue
                            
                            description = line.get("Description") or product_code
                            qty = float(line.get("Amount", 1) or 0.0)
                            price_unit = float(line.get("Price", 0) or 0.0)
                            discount_percent = float(line.get("DiscountPercent", 0) or 0.0)
                            uom_name = (line.get("UnitIDText") or "Cái").strip()
                            note = line.get("DescriptionProduct") or ""
                            misa_product_id = line.get("ProductID") or line.get("ProductId") or None
                            
                            # Xác định loại dòng
                            is_combo_parent = line.get("IsSetProduct", False)
                            is_combo_child = line.get("IsChildProduct", False)
                            
                            # ===== TẠO/LẤY PRODUCT =====
                            if is_combo_parent:
                                # COMBO CHA
                                combo_product = misa_utils.get_or_create_combo_product(
                                    combo_data=line,
                                    children_data=[],
                                    env=self.env,
                                    sale_headers=sale_headers,
                                )
                                product = combo_product or odoo_utils._get_or_create_product(
                                    code=product_code,
                                    name=description,
                                    unit_name=uom_name,
                                    cost=price_unit,
                                    product_type="consu",
                                    purchase_ok=True,
                                    sale_ok=True
                                )
                            elif is_combo_child:
                                # COMBO CON: Bỏ qua không tạo dòng SO
                                _logger.info("ℹ️ Skip combo child line: %s", product_code)
                                continue
                                # Nếu đã có → dùng luôn, KHÔNG cập nhật cost
                            else:
                                # DÒNG THƯỜNG: có giá đầy đủ
                                product = odoo_utils._get_or_create_product(
                                    code=product_code,
                                    name=description,
                                    unit_name=uom_name,
                                    cost=price_unit,
                                    product_type="consu",
                                    purchase_ok=True,
                                    sale_ok=True
                                )
                            
                            # ===== QUY ĐỔI UOM =====
                            qty_for_odoo, price_for_odoo, use_default_uom = self._convert_qty_price_to_default_uom(
                                product=product,
                                misa_uom_text=uom_name,
                                qty=qty,
                                price=price_unit,
                                misa_product_id=misa_product_id,
                                headers=sale_headers
                            )
                            
                            # ===== TẠO SALE ORDER LINE =====
                            line_vals = {
                                'order_id': sale_order.id,
                                'product_id': product.id,
                                'name': description,
                                'product_uom_qty': qty_for_odoo,
                                'price_unit': price_for_odoo,
                                'discount': discount_percent,
                                'note': note,
                            }
                            if not use_default_uom and product.uom_id:
                                line_vals['product_uom'] = product.uom_id.id
                            
                            # Thuế
                            tax_ids = self._tax_ids_from_misa_sale_line(line)
                            if tax_ids:
                                line_vals['tax_id'] = [(6, 0, tax_ids)]
                            else:
                                # MISA không có thuế → Clear thuế
                                line_vals['tax_id'] = [(5, 0, 0)]
                            
                            # Studio fields (Cleaned up)
                            line_vals['x_studio_is_combo_child'] = False
                            line_vals['x_studio_combo_parent_code'] = False
                            
                            # ===== PRODUCTION STATUS FROM MISA =====
                            production_status_text = line.get("CustomField4") or ""
                            if production_status_text:
                                line_vals['x_studio_product_status'] = production_status_text
                            
                            allowed_fields = {'order_id','product_id','name','product_uom_qty','price_unit','discount','note','product_uom','tax_id','x_studio_is_combo_child','x_studio_combo_parent_code','x_studio_product_status'}
                            safe_line_vals = {k: v for k, v in line_vals.items() if k in allowed_fields}
                            self.env['sale.order.line'].create(safe_line_vals)

                        # Confirm -> tạo picking theo từng SO/warehouse
                        # Invalidate ORM cache để mrp thấy được phantom BOM vừa tạo trong cùng transaction
                        self.env.flush_all()
                        self.env.invalidate_all()
                        sale_order.action_confirm()

                        # Đặt tên picking: base_pick + hậu tố kho để unique
                        pick_base = base_pick_name or order_ref_base
                        desired_pick_name = f"{pick_base}-{stock_id}"
                        for picking in sale_order.picking_ids:
                            exists = self.env['stock.picking'].search([('name', '=', desired_pick_name)], limit=1)
                            new_name = f"{desired_pick_name}-{picking.id}" if exists else desired_pick_name
                            if picking.name != new_name:
                                picking.name = new_name
                            _logger.info("📦 Đã gán mã phiếu pick: %s cho SO %s", picking.name, order_ref)

            # --- phân trang ---
            if len(orders) < 20:
                break
            page += 1

        return {'type': 'ir.actions.act_window_close'}
