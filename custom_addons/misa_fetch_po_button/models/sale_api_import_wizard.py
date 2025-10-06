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
        Tax = self.env['account.tax'].with_company(self.env.company)
        TaxGroup = self.env['account.tax.group'].with_company(self.env.company)

        rate = float(rate)
        country_vn = self.env['res.country'].search([('code', '=', 'VN')], limit=1)

        # 1) Lấy/tạo Tax Group "VAT"
        vat_group = TaxGroup.search([
            ('name', 'in', ['VAT', 'Thuế GTGT', 'GTGT']),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not vat_group:
            vat_group = TaxGroup.create({
                'name': 'VAT',
                'company_id': self.env.company.id,
                'country_id': country_vn.id or False,
                'sequence': 10,
            })

        # 2) Tìm thuế cùng % trong công ty
        tax = Tax.search([
            ('type_tax_use', '=', use),
            ('amount_type', '=', 'percent'),
            ('amount', '=', rate),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if tax:
            return tax

        # 3) Tạo thuế mới và gán tax_group_id
        rate_str = str(int(rate)) if float(rate).is_integer() else str(rate)
        new_tax = Tax.create({
            'name': f'VAT VN {rate_str}%',
            'type_tax_use': use,
            'amount_type': 'percent',
            'amount': rate,
            'company_id': self.env.company.id,
            'price_include': False,
            'country_id': country_vn.id or False,
            'tax_group_id': vat_group.id,
            'active': True,
        })
        _logger.info("✅ Tạo mới tax: %s (id=%s)", new_tax.name, new_tax.id)
        return new_tax


    def _tax_ids_from_misa_sale_line(self, l: dict):
        """
        Trả về list tax_id cho dòng SO từ dữ liệu MISA.
        MISA CRM trả: TaxPercentIDText (ví dụ: '8%', '10%', 'KCT')
        """
        kct_markers = {'KCT', 'KHONGCHIU', 'NO_VAT', 'Không chịu thuế', ''}

        tax_text = l.get('TaxPercentIDText', '').strip()

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


    def _update_existing_so_taxes(self, existing_order, product_lines):
        """
        Cập nhật thuế cho SO đã tồn tại.
        So khớp dòng theo ProductIDText và cập nhật tax_id.
        """
        if existing_order.state in ('cancel', 'done'):
            _logger.info("⚠️ SO %s đã ở trạng thái %s, không cập nhật thuế",
                        existing_order.name, existing_order.state)
            return False

        updated_count = 0
        for misa_line in product_lines:
            product_code = misa_line.get("ProductIDText")
            if not product_code:
                continue

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
                    odoo_line[0].write({'tax_id': [(6, 0, tax_ids)]})
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

    def _get_or_create_delivery_contact(self, parent_partner, addr_str, phone=None, province_text=None):
        """
        Tạo/nhặt contact con kiểu 'delivery' dưới parent_partner.
        Ưu tiên set:
          - street = addr_str (full chuỗi)
          - city = province_text nếu có
          - state_id/country_id nếu map được
        Tránh nhân bản: tìm theo (parent_id, type='delivery', street == addr_str) trước.
        """
        Partner = self.env['res.partner']
        country = self._vn_country()
        state = self._vn_state_by_name(province_text) if province_text else False

        # Tìm lại nếu có
        existing = Partner.search([
            ('parent_id', '=', parent_partner.id),
            ('type', '=', 'delivery'),
            ('street', '=', addr_str or ''),
        ], limit=1)
        if existing:
            # cập nhật nhẹ nếu thiếu
            vals_upd = {}
            if country and not existing.country_id:
                vals_upd['country_id'] = country.id
            if state and not existing.state_id:
                vals_upd['state_id'] = state.id
            if province_text and not existing.city:
                vals_upd['city'] = province_text
            if phone and not existing.phone:
                vals_upd['phone'] = phone
            if vals_upd:
                existing.write(vals_upd)
            return existing

        vals = {
            'name': parent_partner.name,          # hoặc đặt nhãn riêng nếu bạn muốn
            'type': 'delivery',
            'parent_id': parent_partner.id,
            'street': addr_str or '',
            'city': province_text or False,
            'phone': phone or False,
            'country_id': country.id if country else False,
            'state_id': state.id if state else False,
            # có thể bổ sung email, mobile... nếu cần
        }
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
        }

        e_accounts = {
            "TIKTOK HOÀNG LONG VŨ",
            "SHOPEE TRANG MILWAUKEE",
            "SHOPEE TRANG TBCN HLV",
            "SHOPEE TRANG DEWALT STANLEY",
            "KHÁCH LẺ KHÔNG LẤY HÓA ĐƠN_SHOPEE STANLEY",
            "KHÁCH LẺ KHÔNG LẤY HÓA ĐƠN_SHOPEE",
            "KHÁCH LẺ KHÔNG LẤY HÓA ĐƠN_SHOPEE TBCN",
            "KHÁCH LẺ KHÔNG LẤY HÓA ĐƠN_TIKTOK",
            "KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE",
            "KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE TBCN",
            "KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE STANLEY",
            "KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_TIKTOK",
            "KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_TIKTOK",
            "TOOL DEWALT",
            "KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE STANLEY",
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
                revenue_status_id = order.get("RevenueStatusID")
                order_ref = order.get("SaleOrderNo")
                order_id = order.get("ID")

                # Bỏ qua đơn đã giao (DeliveryStatusID=2)
                delivery_status = order.get("DeliveryStatusID", "0")
                if delivery_status is not None and str(delivery_status).strip() == "2":
                    _logger.info("⏭️ Bỏ qua SO %s (id=%s) vì Đơn hàng đã giao (DeliveryStatusID=2)", order.get("SaleOrderNo"), order.get("ID"))
                    continue
                
                # Nếu là 'Từ chối ghi' → hủy các SO hiện có trùng tên rồi bỏ qua import
                if revenue_status_id == 4 or status == "từ chối ghi":
                    found = self.env['sale.order'].sudo().search([('name', '=', order_ref)])
                    if found:
                        for so in found:
                            self._force_cancel_sale_order(so, revenue_status_id, status)
                    continue



                # Bỏ qua SO 'Bản nháp' mà không thuộc e_accounts
                if customer_name not in e_accounts and status == "Bản nháp":
                    _logger.info("⏭️ SO %s là 'Bản nháp' và không thuộc e_accounts => bỏ qua", order.get("SaleOrderNo"))
                    continue

                if customer_name in e_accounts and not order.get('DeliveryOrderNumber'):
                    continue

                if customer_name in e_accounts:
                    base_pick_name = order.get('DeliveryOrderNumber')
                else:
                    base_pick_name = order.get('SaleOrderNo')

                # --- Lấy chi tiết dòng hàng ---
                order_id = order.get("ID")
                misa_id_str = str(order_id) if order_id else False  # ### NEW
                payload_detail = misa_config.get_crm_sale_order_detail_payload(order_id)
                product_lines = misa_utils.get_list_product_by_order_crm(order_detail_url, sale_headers, payload_detail)
                _logger.warning("📦 Order product_lines FULL DATA: %s", product_lines)
                if product_lines and len(product_lines) > 0:
                    _logger.warning("📦 Sample line keys: %s", list(product_lines[0].keys()))
                
                
                shipping_address_str = misa_utils.get_shipping_address(
                    sale_order_id=order_id,
                    order_ref=order.get("SaleOrderNo"),
                    token=crm_token
                )
                # tỉnh/thành để map state/city
                province_text = (
                    order.get("ShippingProvinceIDCustomText")
                    or order.get("ShippingProvinceIDText")
                    or order.get("BillingProvinceIDCustomText")
                    or order.get("BillingProvinceIDText")
                )
                phone_text = order.get("Phone")


                # --- Gom dòng theo kho ---
                lines_by_stock = defaultdict(list)
                for l in product_lines:
                    sid = l.get("StockIDText")
                    if sid:
                        lines_by_stock[sid].append(l)

                if not lines_by_stock:
                    _logger.warning("⛔ Không có dòng hàng hợp lệ theo kho cho SO %s", order.get("SaleOrderNo"))
                    continue

                order_ref_base = order.get("SaleOrderNo")
                order_date = parse(order.get("SaleOrderDate")).replace(tzinfo=None)
                if not order_ref_base or not customer_name:
                    _logger.warning("⛔ Thiếu mã đơn hoặc tên khách hàng trong đơn hàng: %s", order)
                    continue

                partner = odoo_utils._get_or_create_partner(customer_name)
                
                    # ===== TẠO/GÁN ĐỊA CHỈ GIAO HÀNG (contact delivery) =====

                delivery_contact = self._get_or_create_delivery_contact(
                    parent_partner=partner,
                    addr_str=shipping_address_str or order.get("ShippingAddress") or order.get("BillingAddress") or order_ref_base,
                    phone=phone_text,
                    province_text=province_text
                )

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
                        if misa_id_str and not existing_order.misa_id:
                            existing_order.misa_id = misa_id_str
                        # >>> CẬP NHẬT THUẾ CHO SO ĐÃ TỒN TẠI <
                        self._update_existing_so_taxes(existing_order, grouped_lines)
                        _logger.info("🔁 SO đã tồn tại: %s, đã cập nhật thuế", order_ref)
                        continue

                    group_total = sum(line_subtotal(l) for l in grouped_lines)
                    sale_order = self.env['sale.order'].create({
                        'name': order_ref,
                        'partner_id': partner.id,
                        'date_order': order_date,
                        'amount_total': group_total,
                        'partner_shipping_id': delivery_contact.id, 
                        'origin':origin,
                        'warehouse_id': warehouse.id,
                        'misa_id': misa_id_str,      
                    })
                    
                    

                    # Thêm line
                    for line in grouped_lines:
                        product_code = line.get("ProductIDText")
                        description = line.get("Description") or product_code
                        qty = float(line.get("Amount", 1) or 0.0)
                        price_unit = float(line.get("Price", 0) or 0.0)
                        discount_percent = float(line.get("DiscountPercent", 0) or 0.0)
                        uom_name = (line.get("UnitIDText") or "Cái").strip()
                        note = line.get("DescriptionProduct") or ""

                        product = odoo_utils._get_or_create_product(
                            code=product_code,
                            name=description,
                            unit_name=uom_name,
                            cost=price_unit,
                            product_type="consu",
                            purchase_ok=True,
                            sale_ok=True
                        )
                        
                        misa_product_id = line.get("ProductID") or line.get("ProductId") or None
                        qty_for_odoo = qty
                        price_for_odoo = price_unit
                        use_default_uom = True
                        
                        
                        qty_for_odoo, price_for_odoo, use_default_uom = self._convert_qty_price_to_default_uom(
                            product=product,
                            misa_uom_text=uom_name,
                            qty=qty,
                            price=price_unit,
                            misa_product_id=misa_product_id,
                            headers=sale_headers
                        )
                        vals_line = {
                            'order_id': sale_order.id,
                            'product_id': product.id,
                            'name': description,
                            'product_uom_qty': qty_for_odoo,
                            'price_unit': price_for_odoo,
                            'discount': discount_percent,
                            'note': note,
                        }
                        if not use_default_uom:
                            vals_line['product_uom'] = product.uom_id.id
                        
                        # VAT cho sale line
                        tax_ids = self._tax_ids_from_misa_sale_line(line)
                        if tax_ids:
                            vals_line['tax_id'] = [(6, 0, tax_ids)]

                        self.env['sale.order.line'].create(vals_line)       

                        # self.env['sale.order.line'].create({
                        #     'order_id': sale_order.id,
                        #     'product_id': product.id,
                        #     'name': description,
                        #     'product_uom_qty': qty,
                        #     'price_unit': price_unit,
                        #     'discount': discount_percent
                        # })

                    # Confirm để tạo picking
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
                            # >>> CẬP NHẬT THUẾ CHO SO ĐÃ TỒN TẠI <
                            self._update_existing_so_taxes(existing_order, grouped_lines)
                            _logger.info("🔁 SO đã tồn tại: %s, đã cập nhật thuế", order_ref)
                            continue

                        group_total = sum(line_subtotal(l) for l in grouped_lines)
                        sale_order = self.env['sale.order'].create({
                            'name': order_ref,
                            'partner_id': partner.id,
                            'date_order': order_date,
                            'partner_shipping_id': delivery_contact.id,
                            'amount_total': group_total,       # có thể để Odoo tự tính lại sau khi tạo line
                            'warehouse_id': warehouse.id,
                            'origin': origin,
                            'misa_id': misa_id_str,
                        })

                        # Thêm line
                        for line in grouped_lines:
                            product_code = line.get("ProductIDText")
                            description = line.get("Description") or product_code
                            qty = float(line.get("Amount", 1) or 0.0)
                            price_unit = float(line.get("Price", 0) or 0.0)
                            discount_percent = float(line.get("DiscountPercent", 0) or 0.0)
                            uom_name = (line.get("UnitIDText") or "Cái").strip()
                            note = line.get("DescriptionProduct") or ""

                            product = odoo_utils._get_or_create_product(
                                code=product_code,
                                name=description,
                                unit_name=uom_name,
                                cost=price_unit,
                                product_type="consu",
                                purchase_ok=True,
                                sale_ok=True
                            )

                            line_vals = {
                                'order_id': sale_order.id,
                                'product_id': product.id,
                                'name': description,
                                'product_uom_qty': qty,
                                'price_unit': price_unit,
                                'discount': discount_percent,
                                'note': note,
                            }

                            # >>> NEW: map VAT từ dữ liệu MISA -> tax_id (many2many)
                            tax_ids = self._tax_ids_from_misa_sale_line(line)
                            if tax_ids:
                                line_vals['tax_id'] = [(6, 0, tax_ids)]

                            self.env['sale.order.line'].create(line_vals)

                        # Confirm -> tạo picking theo từng SO/warehouse
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
                _logger.warning("🔍 Order level VAT: VATRate=%s, VATPercent=%s, TaxRate=%s", 
                    order.get('VATRate'), 
                    order.get('VATPercent'),
                    order.get('TaxRate'))

            # --- phân trang ---
            if len(orders) < 20:
                break
            page += 1

        return {'type': 'ir.actions.act_window_close'}
