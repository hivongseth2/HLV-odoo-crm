import requests
from odoo import models, fields, api
from datetime import datetime, timedelta
from dateutil import parser  # để xử lý ISO datetime
import logging
from dateutil.parser import parse

_logger = logging.getLogger(__name__)

class SaleApiImportWizard(models.TransientModel):
    _name = 'sale.api.import.wizard'
    _description = 'Import Sale Orders from MISA API'

    from_date = fields.Date(string="Từ ngày", required=True)
    to_date = fields.Date(string="Đến ngày", required=True)


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
             "HCM_SHOWROOM":"TSNSR/Stock"
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

        page = 1
        while True:
            payload = misa_config.get_crm_sale_order_payload(start_datetime,end_datetime, page)
            try:
                response = requests.post(orders_url, headers=sale_headers, json=payload) 
                response.raise_for_status()
                orders = response.json().get("Data", [])
            except Exception as e:
                
                raise Exception(f"Lỗi khi lấy đơn hàng từ API MISA: {e} {payload}")

            for order in orders:

            # có order thì đi gọi lấy danh sách sản phẩm trong product đó 
            
            
            #AccountIDText: TIKTOK HOÀNG LONG VŨ , SHOPEE TRANG MILWAUKEE, SHOPEE TRANG TBCN HLV,SHOPEE TRANG DEWALT STANLEY
                # delivery_order_number = order.get('DeliveryOrderNumber')
                customer_name = order.get("AccountIDText") or order.get("SaleOrderName")
                # if customer_name in e_accounts and not delivery_order_number:
                #     continue
                status = order.get("RevenueStatusIDText")
                
                if customer_name not in e_accounts and status == "Bản nháp": 
                    _logger.info("⏭️ Đơn hàng %s là 'Bản nháp' và không thuộc e_accounts => bỏ qua", order.get("SaleOrderNo")) 
                    continue
                
                if customer_name in e_accounts and not order.get('DeliveryOrderNumber'):
                    continue

                
                if customer_name in e_accounts:
                    delivery_order_number = order.get('DeliveryOrderNumber')
                else:
                    delivery_order_number = order.get('SaleOrderNo')

                id = order.get("ID")
                payload = misa_config.get_crm_sale_order_detail_payload(id)


                # === LẤY DÒNG HÀNG CỦA ĐƠN ===
                product_lines = misa_utils.get_list_product_by_order_crm(order_detail_url, sale_headers, payload)
                _logger.warning("📦 Order product_lines %s", product_lines)

                # === GOM NHÓM THEO KHO ===
                from collections import defaultdict
                lines_by_stock = defaultdict(list)
                for l in product_lines:
                    sid = l.get("StockIDText")
                    if sid:
                        lines_by_stock[sid].append(l)

                if not lines_by_stock:
                    _logger.warning("⛔ Không có dòng hàng hợp lệ theo kho cho SO %s", order.get("SaleOrderNo"))
                    continue

                # === LẶP TỪNG KHO: TẠO 1 SO / 1 KHO ===
                base_order_ref = order.get("SaleOrderNo")
                amount_total_all = float(order.get("SaleOrderAmount", 0.0))  # tổng của MISA (chỉ để tham khảo)
                order_date = parse(order.get("SaleOrderDate")).replace(tzinfo=None)
                if not base_order_ref or not customer_name:
                    _logger.warning("⛔ Thiếu mã đơn hoặc tên khách hàng trong đơn hàng: %s", order)
                    continue

                partner = odoo_utils._get_or_create_partner(customer_name)

                for stock_id, grouped_lines in lines_by_stock.items():
                    if stock_id not in stock_mapping:
                        _logger.warning("📛 Kho %s không nằm trong mapping, bỏ nhóm kho này của đơn %s", stock_id, base_order_ref)
                        continue

                    # tìm location/warehouse cho kho này
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

                    # Đặt hậu tố để phân biệt theo kho (ví dụ TSN, KBC, KHD, TSNSR)
                    suffix = stock_id  # hoặc map sang mã ngắn nếu muốn
                    order_ref = f"{base_order_ref}-{suffix}"

                    # Tránh tạo trùng
                    existing_order = self.env['sale.order'].search([('name', '=', order_ref)], limit=1)
                    if existing_order:
                        _logger.info("🔁 Bỏ qua SO đã tồn tại: %s", order_ref)
                        continue

                    # Tính tổng tiền theo nhóm (đơn giản: qty * price * (1 - discount%))
                    def line_subtotal(l):
                        qty = float(l.get("Amount", 1) or 0.0)
                        price = float(l.get("Price", 0) or 0.0)
                        disc = float(l.get("DiscountPercent", 0) or 0.0)
                        return qty * price * (1.0 - disc/100.0)

                    group_total = sum(line_subtotal(l) for l in grouped_lines)

                    sale_order = self.env['sale.order'].create({
                        'name': order_ref,
                        'partner_id': partner.id,
                        'date_order': order_date,
                        'amount_total': group_total,   # để hiển thị/đối chiếu (Odoo sẽ tự tính lại khi cần)
                        'warehouse_id': warehouse.id,  # ⬅️ ấn định kho theo nhóm
                    })

                    for line in grouped_lines:
                        product_code = line.get("ProductIDText")
                        description  = line.get("Description") or product_code
                        qty          = float(line.get("Amount", 1) or 0.0)
                        price_unit   = float(line.get("Price", 0) or 0.0)
                        discount_pct = float(line.get("DiscountPercent", 0) or 0.0)
                        uom_name     = (line.get("UnitIDText") or "Cái").strip()

                        product = odoo_utils._get_or_create_product(
                            code=product_code,
                            name=description,
                            unit_name=uom_name,
                            cost=price_unit,
                            product_type="consu",
                            purchase_ok=False,
                            sale_ok=False
                        )
                        self.env['sale.order.line'].create({
                            'order_id': sale_order.id,
                            'product_id': product.id,
                            'name': description,
                            'product_uom_qty': qty,
                            'price_unit': price_unit,
                            'discount': discount_pct
                        })

                    # Confirm để sinh picking theo kho tương ứng
                    sale_order.action_confirm()

                    # Gán tên phiếu pick theo DeliveryOrderNumber (nếu có) + hậu tố kho để unique
                    # Với e_accounts: lấy DeliveryOrderNumber; ngược lại: dùng base_order_ref
                    if customer_name in e_accounts:
                        base_pick = order.get('DeliveryOrderNumber') or order_ref
                    else:
                        base_pick = order.get('SaleOrderNo') or order_ref

                    pick_suffix = suffix  # ví dụ HCM/KBC/HIENDUC/HCM_SHOWROOM
                    desired_pick_name = f"{base_pick}-{pick_suffix}"

                    # Có thể có nhiều picking nếu rule/route đặc biệt; set cho từng cái chưa set
                    for picking in sale_order.picking_ids:
                        # Tránh đụng tên đã tồn tại
                        exists = self.env['stock.picking'].search([('name', '=', desired_pick_name)], limit=1)
                        if exists:
                            new_name = f"{desired_pick_name}-{picking.id}"
                        else:
                            new_name = desired_pick_name
                        if picking.name != new_name:
                            picking.name = new_name
                        _logger.info("📦 Đã gán mã phiếu pick: %s cho SO %s", picking.name, order_ref)
