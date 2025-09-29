import requests
from odoo import models, fields, api
from datetime import datetime, timedelta
from dateutil import parser  # để xử lý ISO datetime
import logging
from dateutil.parser import parse
from collections import defaultdict
import uuid

_logger = logging.getLogger(__name__)

class SaleApiImportWizard(models.TransientModel):
    _name = 'sale.api.import.wizard'
    _description = 'Import Sale Orders from MISA API'

    from_date = fields.Date(string="Từ ngày", required=True)
    to_date = fields.Date(string="Đến ngày", required=True)
    
    
    
    
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
        Trả về (qty_base, price_base, uom_is_default)
        - Nếu misa_uom_text == default_uom -> không đổi
        - Nếu khác: thử tìm mapping
            a) Tìm conversion trùng misa_uom_text (đơn vị của dòng)
            b) Nếu không có, tìm conversion trùng default_uom (đơn vị mặc định của product)
        """
        default_uom_name = (product.uom_id and product.uom_id.name) or ""
        if not misa_uom_text or misa_uom_text.strip().lower() == default_uom_name.strip().lower():
            return qty, price, True

        conversions = self._misa_fetch_conversion_units(misa_product_id, headers) or []

        # a) TRƯỚC: tìm mapping theo UoM của dòng (ví dụ: dòng là "Hộp", ConversionUnitIDText = "Hộp")
        conv = None
        lower = str(misa_uom_text).strip().lower()
        for c in conversions:
            if (c.get("ConversionUnitIDText") or "").strip().lower() == lower:
                conv = c
                break

        if conv:
            rate = float(conv.get("ConversionRate") or 0.0)
            op_id = int(conv.get("ConversionOperatorID") or 1)  # 1=Nhân, 2=Chia
            if rate <= 0:
                return qty, price, False
            if op_id == 1:   # Nhân: 1 misa_uom = rate * base_uom
                # Dòng đang ở misa_uom, muốn về base -> nhân số lượng, chia đơn giá
                return qty * rate, (price / rate if rate else price), False
            else:            # Chia: 1 misa_uom = (1/rate) * base_uom
                # Dòng đang ở misa_uom, muốn về base -> chia số lượng, nhân đơn giá
                return (qty / rate), (price * rate), False

        # b) SAU: không tìm thấy theo UoM dòng -> thử khớp theo default_uom (ví dụ JSON trả "Mét")
        def_uom_lower = default_uom_name.strip().lower()
        conv2 = None
        for c in conversions:
            if (c.get("ConversionUnitIDText") or "").strip().lower() == def_uom_lower:
                conv2 = c
                break

        if not conv2:
            # Không có mapping nào dùng được
            return qty, price, False

        rate = float(conv2.get("ConversionRate") or 0.0)
        op_id = int(conv2.get("ConversionOperatorID") or 1)
        if rate <= 0:
            return qty, price, False

        # Ở nhánh này ConversionUnitIDText == default_uom_name
        # Ví dụ: "1 Mét = 1/50 Cuộn" (op_id=2 Chia, rate=50)
        # => 1 base(Cuộn) = 50 default(Mét)
        # Dòng đang ở base(Cuộn) -> về default(Mét): qty * 50, price / 50
        if op_id == 2:  # Chia: 1 default = (1/rate) * base  =>  1 base = rate * default
            return qty * rate, (price / rate if rate else price), False
        else:           # Nhân: 1 default = rate * base      =>  1 base = (1/rate) * default
            return (qty / rate), (price * rate), False

    
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
            "KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE STANLEY"
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
                status = order.get("RevenueStatusIDText")

                # Bỏ qua đơn đã giao (DeliveryStatusID=2)
                delivery_status = order.get("DeliveryStatusID", "0")
                if delivery_status is not None and str(delivery_status).strip() == "2":
                    _logger.info("⏭️ Bỏ qua SO %s (id=%s) vì Đơn hàng đã giao (DeliveryStatusID=2)", order.get("SaleOrderNo"), order.get("ID"))
                    continue

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
                _logger.warning("📦 Order product_lines %s", product_lines)
                
                
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
                    # Tránh trùng
                    existing_order = self.env['sale.order'].search([('name', '=', order_ref)], limit=1)
                    if existing_order:
                        if misa_id_str and not existing_order.misa_id:
                            existing_order.misa_id = misa_id_str
                        _logger.info("🔁 Bỏ qua SO đã tồn tại: %s", order_ref)
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

                        existing_order = self.env['sale.order'].search([('name', '=', order_ref)], limit=1)
                        if existing_order:
                            _logger.info("🔁 Bỏ qua SO đã tồn tại: %s", order_ref)
                            continue

                        group_total = sum(line_subtotal(l) for l in grouped_lines)
                        sale_order = self.env['sale.order'].create({
                            'name': order_ref,
                            'partner_id': partner.id,
                            'date_order': order_date,
                            'partner_shipping_id': delivery_contact.id, 
                            'amount_total': group_total,
                            'warehouse_id': warehouse.id,
                            'origin':origin,
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
                            self.env['sale.order.line'].create({
                                'order_id': sale_order.id,
                                'product_id': product.id,
                                'name': description,
                                'product_uom_qty': qty,
                                'price_unit': price_unit,
                                'discount': discount_percent,
                                'note': note,
                            })

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

            # --- phân trang ---
            if len(orders) < 20:
                break
            page += 1

        return {'type': 'ir.actions.act_window_close'}
