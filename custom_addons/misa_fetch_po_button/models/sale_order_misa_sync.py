# models/sale_order_misa_sync.py
import requests
import logging
from odoo import models, fields, api, _
from markupsafe import Markup
from dateutil.parser import parse as dtparse
from odoo.exceptions import UserError
import json

_logger = logging.getLogger(__name__)
class SaleOrder(models.Model):
    _inherit = 'sale.order'

    misa_id = fields.Char(string="MISA ID")                  # ví dụ: "27264"
    misa_form_layout_id = fields.Integer(default=37)         # theo payload mẫu của bạn
    misa_form_type = fields.Integer(default=4)               # theo URL mẫu: .../SaleOrder/37/4
    misa_shipping_address = fields.Char(string="MISA Shipping Address", copy=False, index=True)
    
    

    def _misa_headers(self):
        """Tạo headers CRM MISA (dựa vào utils/config của bạn)."""
        misa_utils = self.env['misa.api.utils']
        misa_config = self.env['misa.config']
        crm_token = misa_utils._fetch_login_crm_token()
        return misa_config.get_crm_header(crm_token), crm_token

    def _misa_fetch_order(self):
        """Gọi FormDataNew lấy thông tin chung 1 đơn."""
        self.ensure_one()
        if not self.misa_id:
            raise ValueError(_("Thiếu MISA ID trên đơn bán."))

        headers, _crm_token = self._misa_headers()
        url = f"https://amisapp.misa.vn/crm/g2/api/business/SaleOrder/FormDataNew/SaleOrder/{self.misa_form_layout_id}/{self.misa_form_type}"
        payload = {
            "ID": str(self.misa_id),
            "MISAEntityState": 2,
            "ActiveLayoutCode": None,
            "CustomDicData": None,
        }
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        js = r.json()
        _logger.info(
            "MISA FormDataNew response for misa_id=%s:\n%s",
            self.misa_id,
            json.dumps(js, ensure_ascii=False, indent=2)
        )
        if not js.get("Success"):
            raise ValueError(_("MISA trả về lỗi (FormDataNew): %s") % js)
        return js.get("Data", {}).get("CurrentData", {})

    def _misa_fetch_lines(self, misa_order_id):
        """Gọi DataSubPaging lấy các dòng sản phẩm (theo cách bạn đang dùng)."""
        self.ensure_one()
        misa_utils = self.env['misa.api.utils']
        misa_config = self.env['misa.config']
        headers, crm_headers = self._misa_headers()

        # bạn đã có sẵn helper get_crm_sale_order_detail_payload + get_list_product_by_order_crm
        order_detail_url = "https://amisapp.misa.vn/crm/g2/api/business/SaleOrder/DataSubPaging"
        payload_detail = misa_config.get_crm_sale_order_detail_payload(misa_order_id)
        product_lines = misa_utils.get_list_product_by_order_crm(order_detail_url, headers, payload_detail)
        logging.debug("productline", product_lines)
        return product_lines or []
        # ===== Helpers lấy/convert UoM từ MISA =====

    
    def _misa_fetch_conversion_units(self, product_id, headers):
        """
        Gọi Product/DataSubPaging để lấy quy đổi UoM cho 1 sản phẩm (payload theo yêu cầu của bạn).
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
            "SessionID": "864e2811-5edd-5ccc-6b85-178b59007e93",
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


    # ---------------- core sync ----------------

    def _ensure_single_picking(self, desired_name=None):
        """Đảm bảo chỉ còn 1 picking chưa done; đặt tên theo desired_name (unique)."""
        self.ensure_one()
        Picking = self.env['stock.picking']

        not_done = self.picking_ids.filtered(lambda p: p.state not in ('done','cancel'))
        done_ones = self.picking_ids.filtered(lambda p: p.state == 'done')

        keep = False
        if not_done:
            keep = not_done[0]
            for p in not_done[1:]:
                try:
                    if p.state not in ('cancel','done'):
                        if hasattr(p, 'action_cancel'):
                            p.action_cancel()
                    p.unlink()
                except Exception as e:
                    _logger.warning("Không xoá được picking %s: %s", p.name, e)
        elif done_ones:
            keep = done_ones[0]
        else:
            # nếu không có picking -> confirm lại để phát sinh (nếu cần)
            if self.state in ('draft','sent'):
                self.action_confirm()
            keep = self.picking_ids[:1]

        if keep and desired_name:
            exists = Picking.search([('name', '=', desired_name), ('id', '!=', keep.id)], limit=1)
            new_name = f"{desired_name}-{keep.id}" if exists else desired_name
            if keep.name != new_name:
                keep.name = new_name

    # ==== Helpers VAT (chuẩn "VAT VN X%") ====
    def _get_or_create_vn_vat(self, rate, use='sale'):
        Tax = self.env['account.tax'].with_company(self.env.company)
        TaxGroup = self.env['account.tax.group'].with_company(self.env.company)

        rate = float(rate)
        # lấy country VN, fallback theo name
        country_vn = self.env['res.country'].search([('code', '=', 'VN')], limit=1)
        if not country_vn:
            country_vn = self.env['res.country'].search([('name', 'ilike', 'Viet%')], limit=1)

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

        rate_str = str(int(rate)) if float(rate).is_integer() else str(rate)
        vat_name = f'VAT VN {rate_str}%'

        tax = Tax.search([
            ('type_tax_use', '=', use),
            ('amount_type', '=', 'percent'),
            ('amount', '=', rate),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if tax:
            # sửa lại tên/country nếu chưa chuẩn
            if tax.name != vat_name or tax.country_id.code != 'VN':
                tax.write({
                    'name': vat_name,
                    'country_id': country_vn.id or self.env.company.country_id.id,
                    'tax_group_id': vat_group.id,
                })
            return tax

        return Tax.create({
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


    def _tax_ids_from_misa_line(self, line):
        """Trích xuất %VAT từ line MISA (TaxPercentIDText) → trả về list tax_id."""
        txt = str(line.get('TaxPercentIDText') or '').strip()
        kct = {'', 'KCT', 'KHONGCHIU', 'NO_VAT', 'Không chịu thuế'}
        if not txt or txt.upper() in kct:
            return []
        try:
            rate = float(txt.replace('%', '').strip())
        except Exception:
            return []
        tax = self._get_or_create_vn_vat(rate, use='sale')
        return [tax.id] if tax else []


    def action_resync_from_misa_hard(self):
        self.ensure_one()
        env = self.env
        odoo_utils = env['odoo.utils']

        # Lấy headers cho các call phụ (convert UoM)
        headers, crm_headers = self._misa_headers()

        # 1) Lấy dữ liệu MISA trước khi đụng dữ liệu hiện hữu
        data = self._misa_fetch_order()
        misa_order_id = data.get("ID") or data.get("CustomID") or self.misa_id
        lines = self._misa_fetch_lines(misa_order_id)
         # === THÊM MỚI: Kiểm tra trạng thái "Từ chối ghi" ===
        revenue_status_id = data.get("RevenueStatusID")
        revenue_status_text = (data.get("RevenueStatusIDText") or "").strip().lower()

        
        # 2) Chặn các trường hợp không an toàn
        if any(p.state == 'done' for p in self.picking_ids):
            # raise UserError(_("Không thể xoá & tạo lại vì có phiếu giao đã 'done'."))
            return self._partial_resync_open_pickings_when_done_present(data, lines, headers)
        if self.invoice_ids.filtered(lambda m: m.state == 'posted'):
            raise UserError(_("Không thể xoá & tạo lại vì đã có hoá đơn 'posted'."))

        
        # ===== Xác định warehouse theo dòng đầu tiên có StockIDText =====
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

        old_wh = None
        stock_id = None
        zns = False


        # Tìm dòng đầu tiên có StockIDText hợp lệ
        for l in (lines or []):
            sid = (l.get("CustomField2") or "").strip()
            _logger.info("🏭 Lấy warehouse từ dòng MISA: %s", sid)
            if sid:
                stock_id = sid
                break

        if stock_id and stock_id in stock_mapping:
            location_name = stock_mapping[stock_id]
            location = self.env['stock.location'].search([
                ('complete_name', '=', location_name)
            ], limit=1)

            if location and location.warehouse_id:
                old_wh = location.warehouse_id
                _logger.info("🏭 Lấy warehouse từ dòng MISA: %s → %s", stock_id, old_wh.name)
            else:
                _logger.warning("⚠️ Không tìm thấy location/warehouse cho %s", location_name)
        else:
            _logger.warning("⚠️ Không xác định được StockIDText hợp lệ, fallback warehouse None")

        order_no_fallback = self.name


        # ===== 3) HỦY PICKINGS CHƯA DONE (unreserve -> cancel move -> cancel picking) =====
        picks_open = self.picking_ids.sudo().filtered(lambda p: p.state not in ('done', 'cancel'))
        for p in picks_open:
            # a) reset qty_done (nếu có)
            if p.move_line_ids:
                p.move_line_ids.filtered(lambda ml: getattr(ml, 'qty_done', 0)).write({'qty_done': 0})

            # b) unreserve các move còn mở
            try:
                mvs = p.move_ids_without_package.filtered(lambda m: m.state not in ('done', 'cancel'))
                if mvs:
                    if hasattr(mvs, '_do_unreserve'):
                        mvs._do_unreserve()
                    elif hasattr(mvs, 'do_unreserve'):
                        mvs.do_unreserve()
            except Exception as e:
                _logger.warning("Unreserve picking %s lỗi: %s", p.name, e)

            # c) cancel move rồi cancel picking
            try:
                mvs_to_cancel = p.move_ids_without_package.filtered(lambda m: m.state not in ('done', 'cancel'))
                if mvs_to_cancel:
                    mvs_to_cancel._action_cancel()
            except Exception as e:
                _logger.warning("Cancel move của picking %s lỗi: %s", p.name, e)

            try:
                if hasattr(p, 'button_cancel'):
                    p.button_cancel()
                else:
                    p.action_cancel()
            except Exception as e:
                _logger.warning("Huỷ picking %s lỗi: %s", p.name, e)
                # thử lại lần nữa sau khi unreserve/cancel move
                try:
                    if hasattr(p, 'button_cancel'):
                        p.button_cancel()
                    else:
                        p.action_cancel()
                except Exception as e2:
                    raise UserError(_("Không thể hủy phiếu giao %s: %s") % (p.name, e2))

        # ===== 4) HỦY SALE ORDER (giống hành vi UI) =====
        if self.state != 'cancel':
            try:
                self.sudo().action_cancel()
            except Exception as e:
                _logger.warning("action_cancel SO lỗi: %s", e)
                # một số DB cần cancel line trước
                try:
                    if hasattr(self.order_line, '_action_cancel'):
                        self.order_line.sudo()._action_cancel()
                    self.sudo().write({'state': 'cancel'})
                except Exception as e2:
                    raise UserError(_("Không thể hủy đơn bán hàng: %s") % e2)

        self.env.invalidate_all()

        # Fallback an toàn: chỉ ép cancel nếu không còn picking mở & không có invoice posted
        still_open_picks = self.picking_ids.filtered(lambda p: p.state not in ('cancel', 'done'))
        has_posted_inv = bool(self.invoice_ids.filtered(lambda inv: inv.state == 'posted'))
        if self.state != 'cancel':
            if not still_open_picks and not has_posted_inv:
                self.sudo().write({'state': 'cancel'})
            else:
                raise UserError(_("Đơn bán chưa về trạng thái 'cancel'. Còn chứng từ ràng buộc (picking hoặc hóa đơn)."))

        # ===== 5) XÓA PICKINGS (đều đã cancel) =====
        for p in self.picking_ids:
            if p.state != 'done':
                try:
                    if p.state != 'cancel':
                        if hasattr(p, 'button_cancel'):
                            p.sudo().button_cancel()
                        else:
                            p.sudo().action_cancel()
                    p.sudo().unlink()
                except Exception as e:
                    raise UserError(_("Không thể xóa picking %s: %s") % (p.name, e))

        # ===== 6) XÓA INVOICE ở draft/cancel (nếu có) =====
        for inv in self.invoice_ids:
            if inv.state == 'draft':
                try:
                    if hasattr(inv, 'button_cancel'):
                        inv.button_cancel()
                    elif hasattr(inv, 'action_cancel'):
                        inv.action_cancel()
                except Exception:
                    pass
                inv.unlink()
            elif inv.state == 'cancel':
                inv.unlink()

        # ===== 7) XÓA SALE ORDER =====
        try:
            old_name = self.name
            # Đổi tên đơn cũ để không trùng lặp nếu unlink thất bại
            self.sudo().write({'name': f"{old_name}_DEL_{self.id}"})
            _logger.info("🔄 Đã đổi tên SO cũ thành %s để tránh trùng lặp", self.name)
            
            # Sau đó mới thực hiện xóa
            self.sudo().unlink()
            _logger.info("✅ Đã xóa SO cũ thành công")
        except Exception as e:
            # Nếu không xóa được (do ràng buộc database), ít nhất tên đã được đổi
            _logger.warning("⚠️ Không thể xóa SO cũ (unlink) nhưng đã đổi tên: %s", e)

        # ===== 8) TẠO LẠI TỪ MISA =====
   

        # ===== 8) TẠO LẠI TỪ MISA =====
        # Fetch OwnerIDText, SaleOrderDate, ShippingContactIDText, httt, htgh từ MISA
        owner_date = {}
        try:
            owner_date = env['misa.api.utils'].get_saleorder_owner_and_date(misa_order_id, headers) or {}
        except Exception as _e:
            _logger.warning("Không lấy được thông tin chi tiết cho SO=%s: %s", misa_order_id, _e)

        # Khách hàng (partner_id) LUÔN lấy từ AccountIDText
        # Địa chỉ giao hàng/lập hóa đơn lấy từ ShippingContactIDText
        partner_name  = data.get("AccountIDText") or data.get("BillingAccountIDText") or _("Khách hàng MISA")
        shipping_contact_name = owner_date.get('shipping_contact') or data.get("ShippingContactIDText")
        
        # --- NEW LOGIC: Sync from MISA Account API first ---
        account_id = data.get("AccountID") or data.get("AccountId")
        partner = None
        misa_code = None
        tax_code = None
        if account_id:
            partner = env['misa.api.utils']._sync_customer_from_misa_account_api(account_id, headers)
            # Lấy mã CRM dù có tìm thấy partner hay không — dùng cho fallback và ghi vào liên hệ con
            try:
                ident = env['misa.api.utils'].get_account_identity(account_id, headers) or {}
                misa_code = ident.get("account_number") or ident.get("id")
                tax_code = ident.get("taxcode")
            except Exception:
                pass
        if not partner:
            partner = odoo_utils._get_or_create_partner(partner_name, misa_code=misa_code, tax_code=tax_code)
        partner = partner.commercial_partner_id or partner

        # Địa chỉ/phone KHÔNG cập nhật vào liên hệ cha — ghi vào liên hệ con (delivery contact) bên dưới

        crm_order_no = str(data.get("SaleOrderNo") or "").strip()
        crm_order_name = str(data.get("SaleOrderName") or "").strip()
        order_no = (
            crm_order_no
            or crm_order_name
            or order_no_fallback
        )
        # Ưu tiên lấy OtherSysOrderCode, fallback về DeliveryOrderNumber
        delivery_no = (
            owner_date.get("other_sys_order_code")
            or owner_date.get("delivery_order_number")
            or data.get("DeliveryOrderNumber")
            or order_no
        )
        # delivery_no   = data.get("OtherSysOrderCode") or data.get("DeliveryOrderNumber") or order_no
        book_date     = data.get("BookDate") or data.get("InvoiceDate") or data.get("DeliveryDate")
        deadline_date_raw = data.get("DeadlineDate")
        shipping_address_raw = (data.get("ShippingAddress") or "").strip()
        shipping_addr = shipping_address_raw or data.get("BillingAddress") or ''
        origin        = crm_order_name or ''

        # Địa chỉ giao hàng và lập hóa đơn sử dụng ShippingContactIDText
        try:
            # Danh sách e_accounts để xác định khách hàng TMĐT
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
                "TOOL DEWALT",
            }
            delivery_contact = env['sale.api.import.wizard']._get_or_create_delivery_contact(
                parent_partner=partner,
                addr_str=shipping_addr,
                phone=data.get("Phone"),
                province_text=data.get("ShippingProvinceIDText") or data.get("BillingProvinceIDText") ,
                contact_name=shipping_contact_name.strip() if shipping_contact_name else None,
                is_e_account=(partner_name in e_accounts)
            )
            shipping_id = delivery_contact.id
        except Exception as e:
            _logger.warning("Không set delivery contact: %s", e)
            shipping_id = False
            
        zns = bool(data.get("CustomField23", False))

        vals_create = {
            'name': order_no,
            'partner_id': partner.id,
            'origin': origin,
            'warehouse_id': old_wh.id if old_wh else False,
            'misa_id': str(misa_order_id) if misa_order_id else False,
            'misa_shipping_address': shipping_address_raw or False,
            'partner_shipping_id': shipping_id,
            'partner_invoice_id': partner.id,
            'x_studio_zns': zns,
            'x_studio_sdt_giao_hang': data.get('Phone') or False
        }
        
        from dateutil.parser import parse as dtparse
        if book_date:
            try:
                vals_create['date_order'] = dtparse(book_date).replace(tzinfo=None)
            except Exception:
                pass
        if deadline_date_raw:
                    try:
                        vals_create['commitment_date'] = dtparse(deadline_date_raw).replace(tzinfo=None)
                    except Exception:
                        pass
        # Sync x_studio_misa_saler_code, x_studio_misa_order_date, misa_delivery, httt, htgh
        if owner_date.get('owner_code'):
            vals_create['x_studio_misa_saler_code'] = owner_date['owner_code']
        if owner_date.get('sale_order_date'):
            vals_create['x_studio_misa_order_date'] = owner_date['sale_order_date']
        if owner_date.get('misa_delivery'):
            vals_create['x_studio_misa_delivery'] = owner_date['misa_delivery']
        if owner_date.get('httt'):
            vals_create['x_studio_httt'] = owner_date['httt']
        if owner_date.get('htgh'):
            vals_create['x_studio_htgh'] = owner_date['htgh']
        if owner_date.get('misa_note') and 'x_studio_misa_note' in env['sale.order']._fields:
            vals_create['x_studio_misa_note'] = owner_date['misa_note']

        new_so = env['sale.order'].create(vals_create)

        def _flt(x, dv=0.0):
            try:
                return float(x or 0.0)
            except Exception:
                return dv

        # ===== 8.0) BUILD COMBO_PARENT_MAP (HYBRID: Explicit + Smart Matching) =====
        combo_parent_map = {}  # {misa_line_id: parent_code} - DÙNG LINE ID THAY VÌ PRODUCT CODE
        children_by_parent = {}  # {parent_code: [child_data, ...]}
        children_without_parent = []  # Children không có ParentProductID/ParentProductIDText
        
        # Build map: parent_id/code -> parent_code (để tra cứu ngược)
        parent_id_to_code = {}  # {parent_id: parent_code}
        parent_code_set = set()  # Set các parent_code để kiểm tra
        
        _logger.info("📦 Bắt đầu build combo map từ %s dòng", len(lines or []))
        
        # Bước 1: Scan tất cả parent để build mapping ID->CODE
        for line in (lines or []):
            if line.get("IsSetProduct"):  # Đây là combo parent
                parent_code = (line.get("ProductIDText") or "").strip()
                parent_id = line.get("ProductID") or line.get("ProductId")
                
                if parent_code:
                    parent_code_set.add(parent_code)
                    if parent_id:
                        parent_id_to_code[str(parent_id)] = parent_code
                    _logger.info("🔵 Parent found: ID=%s → CODE='%s'", parent_id, parent_code)
        
        # Bước 2: Scan children - ưu tiên explicit, thu thập children_without_parent cho smart matching
        for ch in (lines or []):
            if not ch.get("IsChildProduct"):
                continue
            
            child_code = (ch.get("ProductIDText") or "").strip()
            child_misa_id = ch.get("ID")  # MISA line ID (unique)
            p_id = ch.get("ParentProductID") or ch.get("ParentProductId")
            p_code = (ch.get("ParentProductIDText") or "").strip()
            
            _logger.info("🔹 Child: '%s' (MISA ID=%s) | ParentID=%s | ParentCode='%s'", 
                        child_code, child_misa_id, p_id, p_code)
            
            # Xác định parent_code bằng explicit data
            parent_code = None
            
            # Ưu tiên 1: ParentProductIDText (chính xác nhất)
            if p_code and p_code in parent_code_set:
                parent_code = p_code
                _logger.info("   ✅ Dùng ParentProductIDText: '%s'", parent_code)
            
            # Ưu tiên 2: Tra ParentProductID → parent_code
            elif p_id and str(p_id) in parent_id_to_code:
                parent_code = parent_id_to_code[str(p_id)]
                _logger.info("   ✅ Tra ParentProductID=%s → '%s'", p_id, parent_code)
            
            # Lưu mapping hoặc đưa vào danh sách cần smart matching
            if parent_code and child_misa_id:
                combo_parent_map[child_misa_id] = parent_code  # KEY = MISA LINE ID
                children_by_parent.setdefault(parent_code, []).append(ch)
                _logger.info("   🔗 Explicit map: MISA_ID=%s ('%s') → parent '%s'", 
                            child_misa_id, child_code, parent_code)
            else:
                children_without_parent.append(ch)
                _logger.info("   ⏳ Child '%s' (ID=%s) cần smart matching", child_code, child_misa_id)
        
        # Bước 3: Smart matching cho children không có explicit parent (dựa trên SortOrder)
        if children_without_parent:
            _logger.info("🔄 Smart matching cho %s children...", len(children_without_parent))
            
            # Tạo set để track children đã match (dùng ID duy nhất)
            matched_child_ids = set()
            current_parent_code = None
            
            for it in (lines or []):
                if it.get("IsSetProduct"):
                    current_parent_code = (it.get("ProductIDText") or "").strip()
                    _logger.info("   🔵 Smart match context: parent='%s'", current_parent_code)
                elif it.get("IsChildProduct") and current_parent_code:
                    child_code = (it.get("ProductIDText") or "").strip()
                    child_misa_id = it.get("ID")  # ID duy nhất từ MISA
                    
                    # Kiểm tra: child này có trong danh sách cần match + chưa được match
                    is_in_list = any(c.get("ID") == child_misa_id for c in children_without_parent)
                    already_matched = child_misa_id in matched_child_ids
                    
                    if is_in_list and not already_matched:
                        combo_parent_map[child_misa_id] = current_parent_code  # KEY = MISA LINE ID
                        children_by_parent.setdefault(current_parent_code, []).append(it)
                        matched_child_ids.add(child_misa_id)  # Đánh dấu đã match
                        _logger.info("   🔗 Smart map: MISA_ID=%s ('%s') → parent '%s'", 
                                   child_misa_id, child_code, current_parent_code)
        
        _logger.info("🔍 Combo map cuối cùng: %s", combo_parent_map)
        _logger.info("📊 Children by parent: %s", {k: len(v) for k, v in children_by_parent.items()})

        # ===== 8.0a) ĐỒNG BỘ TÊN SẢN PHẨM TỪ MISA (TRƯỚC KHI TẠO LINES) =====
        _logger.info("🔄 Đồng bộ tên sản phẩm từ MISA cho đơn %s...", order_no)
        synced_count = 0
        for ln in (lines or []):
            # Bỏ qua combo child
            if ln.get("IsChildProduct"):
                continue
            
            product_code = (ln.get("ProductIDText") or "").strip()
            product_name = ln.get("Description") or product_code
            
            if product_code and product_name:
                result = odoo_utils._sync_product_name_from_misa(product_code, product_name)
                if result:
                    synced_count += 1
        
        if synced_count > 0:
            _logger.info("✅ Đã đồng bộ tên cho %d sản phẩm từ MISA", synced_count)

        # ===== 8.0b) TẠO/CẬP NHẬT COMBO PRODUCTS TRƯỚC KHI TẠO LINES =====
        misa_utils = env['misa.api.utils']
        combo_products_created = set()  # Track các combo đã xử lý
        
        for ln in (lines or []):
            if not ln.get("IsSetProduct"):
                continue
            
            combo_code = (ln.get("ProductIDText") or "").strip()
            if not combo_code or combo_code in combo_products_created:
                continue
            
            _logger.info("🔧 Tạo/cập nhật combo product: %s", combo_code)
            
            # Lấy children từ map đã build (TRA TRỰC TIẾP THEO CODE)
            children_for_parent = children_by_parent.get(combo_code, [])
            
            if children_for_parent:
                _logger.info("   📋 Tìm thấy %s children cho combo '%s'", len(children_for_parent), combo_code)
            else:
                _logger.warning("   ⚠️ KHÔNG tìm thấy children cho combo '%s'", combo_code)
            
            try:
                # Gọi helper từ misa_utils để tạo/cập nhật combo
                misa_utils.get_or_create_combo_product(
                    combo_data=ln,
                    children_data=children_for_parent,
                    env=env,
                    sale_headers=headers
                )
                combo_products_created.add(combo_code)
                _logger.info("✅ Đã xử lý combo product: %s", combo_code)
            except Exception as e:
                _logger.exception("❌ Lỗi tạo combo product %s: %s", combo_code, e)

        # ===== 8.1) THÊM LINES (có quy đổi UoM nếu khác mặc định) =====
        # 🔥 Build set các combo codes đã có BOM để skip children
        combo_codes_with_bom = set()
        for combo_code_check in combo_products_created:
            # Kiểm tra xem combo này đã có BOM chưa
            combo_prod_check = env['product.product'].search([('default_code', '=', combo_code_check)], limit=1)
            if combo_prod_check:
                has_bom = env['mrp.bom'].search_count([
                    ('product_tmpl_id', '=', combo_prod_check.product_tmpl_id.id),
                    ('type', '=', 'phantom'),
                    ('active', '=', True)
                ]) > 0
                if has_bom:
                    combo_codes_with_bom.add(combo_code_check)
                    _logger.info("📦 Combo '%s' có BOM Kit → sẽ skip children từ MISA", combo_code_check)

        for ln in (lines or []):
            product_code = ln.get("ProductIDText")
            description  = ln.get("Description") or product_code
            qty          = _flt(ln.get("Amount"), 0.0)
            price_unit   = _flt(ln.get("Price"), 0.0)
            discount_pct = _flt(ln.get("DiscountPercent"), 0.0)
            uom_name     = (ln.get("UnitIDText") or "Cái").strip()
            note_text    = (ln.get("DescriptionProduct")
                or ln.get("Note")
                or "")
            
            tth = (ln.get("CustomField4") or "").strip()
            # Xác định loại dòng (để gán Studio fields)
            is_combo_child = ln.get("IsChildProduct")
            
            # 🔥 SKIP COMBO CHILD NẾU PARENT ĐÃ CÓ BOM KIT
            # (vì BOM Kit sẽ tự động explode ra children trong picking)
            if is_combo_child:
                misa_line_id = ln.get("ID")
                parent_code = combo_parent_map.get(misa_line_id)
                if parent_code and parent_code in combo_codes_with_bom:
                    _logger.info("⏭️ Skip combo child '%s' (parent '%s' có BOM Kit)", product_code, parent_code)
                    continue

            # tạo/lấy product (đơn vị mặc định của Odoo là product.uom_id)
            # sửa purchase_ok và sale_ok True
            product = odoo_utils._get_or_create_product(
                code=product_code,
                name=description,
                unit_name=uom_name,
                cost=price_unit,
                product_type="consu",
                purchase_ok=True,
                sale_ok=True,
            )

            # id sản phẩm bên MISA (để truy bảng quy đổi)
            misa_product_id = ln.get("ProductID") or ln.get("ProductId") or None

            # convert về UoM mặc định nếu dòng đang ở UoM khác
            qty_for_odoo, price_for_odoo, use_default_uom = self._convert_qty_price_to_default_uom(
                product=product,
                misa_uom_text=uom_name,
                qty=qty,
                price=price_unit,
                misa_product_id=misa_product_id,
                headers=headers,
            )

            vals_line = {
                'order_id': new_so.id,
                'product_id': product.id,
                'name': description,
                'product_uom_qty': qty_for_odoo,
                'price_unit': price_for_odoo,
                'discount': discount_pct,
                'note': note_text,
                'x_studio_product_status': tth
            }
            # Nếu có convert, ép UoM line về UoM mặc định của product
            if not use_default_uom and product.uom_id:
                vals_line['product_uom'] = product.uom_id.id

            # Gán thuế (cho CẢ cha lẫn con)
            tax_ids = self._tax_ids_from_misa_line(ln)
            if tax_ids:
                vals_line['tax_id'] = [(6, 0, tax_ids)]
                _logger.info("💰 Gán thuế cho '%s': %s (TaxPercentIDText='%s')", 
                            product_code, tax_ids, ln.get('TaxPercentIDText'))
            else:
                # MISA không có thuế → Clear thuế (không dùng default)
                vals_line['tax_id'] = [(5, 0, 0)]
                _logger.info("⚠️ Không có thuế cho '%s' (TaxPercentIDText='%s') → Clear thuế", 
                            product_code, ln.get('TaxPercentIDText'))
            
            # ===== GÁN 2 TRƯỜNG STUDIO CHO COMBO =====
            if is_combo_child:
                # Dòng combo child - TRA CỨU THEO MISA LINE ID
                vals_line['x_studio_is_combo_child'] = True
                misa_line_id = ln.get("ID")  # MISA line ID (unique)
                parent_code = combo_parent_map.get(misa_line_id, False)
                vals_line['x_studio_combo_parent_code'] = parent_code
                
                if parent_code:
                    _logger.info("✅ Combo child '%s' (MISA_ID=%s) → parent '%s'", 
                               product_code, misa_line_id, parent_code)
                else:
                    _logger.warning("⚠️ Combo child '%s' (MISA_ID=%s) KHÔNG tìm thấy parent trong map!", 
                                  product_code, misa_line_id)
            else:
                # Dòng thường hoặc combo parent
                vals_line['x_studio_is_combo_child'] = False
                vals_line['x_studio_combo_parent_code'] = False
            
            # ===== PRODUCTION STATUS FROM MISA =====
            production_status_text = ln.get("CustomField4") or ""
            if production_status_text:
                vals_line['x_studio_product_status'] = production_status_text
                
            env['sale.order.line'].create(vals_line)

        # ===== 9) Confirm & đặt tên picking theo MISA =====
        if new_so.state in ('draft', 'sent'):
            env.flush_all()
            # Invalidate ORM cache để mrp thấy được phantom BOM vừa tạo trong cùng transaction
            env.invalidate_all()
            new_so.action_confirm()
        if new_so.picking_ids:
            picking = new_so.picking_ids[0]
            desired = delivery_no or order_no
            exists = env['stock.picking'].sudo().with_context(active_test=False).search([
                ('name', '=', desired), 
                ('id', '!=', picking.id)
            ], limit=1)
            picking.name = f"{desired}-{picking.id}" if exists else desired
            picking.partner_id = new_so.partner_id.id
            for extra_picking in (new_so.picking_ids - picking):
                extra_picking.partner_id = new_so.partner_id.id

        # Toast + log
        # new_so.message_post(body=_("Đồng bộ (xoá & tạo lại) thành công: %s") % (delivery_no or order_no))
        new_so.message_post(body=f"Đồng bộ (xoá & tạo lại) thành công: {delivery_no or order_no}")

        


        # Redirect sang SO mới
        form_view_id = self.env.ref('sale.view_order_form').id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'views': [(form_view_id, 'form')],
            'res_id': new_so.id,
            'target': 'current',
        }

    def _sync_so_lines_from_misa_no_picking(self, lines, headers):
        """
        Đưa các dòng SO về đúng như MISA (qty/price/uom) theo UoM mặc định của product.
        KHÔNG group theo product code - mỗi dòng MISA = 1 SOL riêng biệt.
        KHÔNG đụng pickings. Nếu có hoá đơn 'posted' thì KHÔNG nên gọi hàm này.
        """
        self.ensure_one()
        env = self.env
        odoo_utils = env['odoo.utils']
        SaleLine = env['sale.order.line']

        def _flt(x, dv=0.0):
            try:
                return float(x or 0.0)
            except Exception:
                return dv

        posted_inv_exists = bool(self.invoice_ids.filtered(lambda m: m.state == 'posted'))
        
        # ===== Build combo_codes_with_bom để skip children =====
        # Nếu combo parent có BoM Kit, Odoo sẽ tự explode ra picking
        # → không cần thêm children vào SO, tránh trùng lặp
        combo_codes_with_bom = set()
        for ln in (lines or []):
            if ln.get("IsSetProduct"):
                combo_code = (ln.get("ProductIDText") or "").strip()
                if combo_code:
                    prod = env['product.product'].search([('default_code', '=', combo_code)], limit=1)
                    if prod and env['mrp.bom'].search_count([
                        ('product_tmpl_id', '=', prod.product_tmpl_id.id),
                        ('type', '=', 'phantom'),
                        ('active', '=', True)
                    ]) > 0:
                        combo_codes_with_bom.add(combo_code)
                        _logger.info("📦 Combo '%s' có BoM Kit → sẽ skip children từ MISA", combo_code)
        
        # Tạo danh sách các SOL từ MISA (chưa tạo vào DB)
        # Sử dụng tracking theo SortOrder để xác định parent của children
        # (MISA không gửi ParentProductIDText - children xuất hiện ngay sau parent)
        misa_sol_data = []
        current_parent_code = None  # Track combo parent hiện tại theo SortOrder
        
        for ln in (lines or []):
            code = (ln.get("ProductIDText") or "").strip()
            if not code:
                continue
            
            # Nếu đây là combo parent → update current_parent_code
            if ln.get("IsSetProduct"):
                current_parent_code = code
                _logger.info("🔵 Gặp combo parent: '%s'", current_parent_code)
            
            # 🔥 SKIP COMBO CHILDREN nếu parent có BoM Kit
            # (Odoo sẽ tự explode BoM Kit ra picking thay vì thêm trực tiếp)
            # Children được xác định bằng IsChildProduct=true và nằm sau parent theo SortOrder
            if ln.get("IsChildProduct"):
                if current_parent_code and current_parent_code in combo_codes_with_bom:
                    _logger.info("⏭️ Skip combo child '%s' (parent '%s' có BoM Kit)", code, current_parent_code)
                    continue

            desc       = ln.get("Description") or code
            qty        = _flt(ln.get("Amount"), 0.0)
            price      = _flt(ln.get("Price"), 0.0)
            discount   = _flt(ln.get("DiscountPercent"), 0.0)
            uom_name   = (ln.get("UnitIDText") or "Cái").strip()
            misa_pid   = ln.get("ProductID") or ln.get("ProductId")
            note_text  = (ln.get("DescriptionProduct") or ln.get("Note") or "")
            x_studio_product_status = (ln.get("CustomField4") or "").strip()

            # Lấy / tạo product đúng theo mã
            product = odoo_utils._get_or_create_product(
                code=code,
                name=desc,
                unit_name=uom_name,
                cost=price,
                product_type="consu",
                purchase_ok=True,
                sale_ok=True,
            )

            # Convert về UoM mặc định của product
            qty_base, price_base, is_default = self._convert_qty_price_to_default_uom(
                product=product,
                misa_uom_text=uom_name,
                qty=qty,
                price=price,
                misa_product_id=misa_pid,
                headers=headers,
            )

            tax_ids = self._tax_ids_from_misa_line(ln)
            
            misa_sol_data.append({
                'product': product,
                'code': code,
                'name': desc,
                'qty': qty_base,
                'price': price_base,
                'discount': discount,
                'note': note_text,
                'tax_ids': tax_ids,
                'is_default_uom': is_default,
                'status': x_studio_product_status,
            })

        # Lấy danh sách SOL hiện tại
        existing_sols = list(self.order_line)
        
        # Match: Tìm SOL hiện có khớp với từng dòng MISA
        # Ưu tiên match theo: product + qty + price (tránh nhầm lẫn khi có 2 dòng cùng product)
        matched_pairs = []  # [(misa_data, sol)]
        unmatched_misa = list(misa_sol_data)
        unmatched_sols = list(existing_sols)
        
        # Pass 1: Match chính xác (product + qty gần bằng)
        for misa_data in list(unmatched_misa):
            for sol in list(unmatched_sols):
                if (sol.product_id == misa_data['product'] 
                    and abs(sol.product_uom_qty - misa_data['qty']) < 0.01):
                    matched_pairs.append((misa_data, sol))
                    unmatched_misa.remove(misa_data)
                    unmatched_sols.remove(sol)
                    break
        
        # Pass 2: Match theo product (cho các dòng còn lại)
        for misa_data in list(unmatched_misa):
            for sol in list(unmatched_sols):
                if sol.product_id == misa_data['product']:
                    matched_pairs.append((misa_data, sol))
                    unmatched_misa.remove(misa_data)
                    unmatched_sols.remove(sol)
                    break
        
        
        # Kiểm tra warning cho SP có qty giảm dưới delivered (không chặn sync)
        for misa_data, sol in matched_pairs:
            qty_delivered = float(getattr(sol, 'qty_delivered', 0.0) or 0.0)
            new_qty = float(misa_data['qty'] or 0.0)
            
            if new_qty < qty_delivered - 0.001:  # Cho phép sai số nhỏ
                # Log cảnh báo nhưng vẫn tiếp tục sync
                # Odoo sẽ tự xử lý tạo return khi cần thiết
                _logger.warning(
                    "⚠️ SP %s: Số lượng mới (%s) < đã giao (%s). Odoo sẽ tự tạo return nếu cần.",
                    misa_data['code'], new_qty, qty_delivered
                )
        
        # Cập nhật các SOL đã match
        for misa_data, sol in matched_pairs:
            vals_line = {
                'name': misa_data['name'],
                'product_uom_qty': misa_data['qty'],
                'price_unit': misa_data['price'],
                'discount': misa_data['discount'],
                'note': misa_data['note'],
                'x_studio_product_status': misa_data['status'],
            }
            if not misa_data['is_default_uom'] and misa_data['product'].uom_id:
                vals_line['product_uom'] = misa_data['product'].uom_id.id
            
            if misa_data['tax_ids']:
                vals_line['tax_id'] = [(6, 0, misa_data['tax_ids'])]
            else:
                vals_line['tax_id'] = [(5, 0, 0)]
            
            sol.write(vals_line)
            _logger.info("✏️ Cập nhật SOL %s: qty=%.2f", misa_data['code'], misa_data['qty'])
        
        # Tạo mới SOL cho các dòng MISA chưa match
        for misa_data in unmatched_misa:
            vals_line = {
                'order_id': self.id,
                'product_id': misa_data['product'].id,
                'name': misa_data['name'],
                'product_uom_qty': misa_data['qty'],
                'price_unit': misa_data['price'],
                'discount': misa_data['discount'],
                'note': misa_data['note'],
                'x_studio_product_status': misa_data['status'],
            }
            if not misa_data['is_default_uom'] and misa_data['product'].uom_id:
                vals_line['product_uom'] = misa_data['product'].uom_id.id
            
            if misa_data['tax_ids']:
                vals_line['tax_id'] = [(6, 0, misa_data['tax_ids'])]
            else:
                vals_line['tax_id'] = [(5, 0, 0)]
            
            SaleLine.create(vals_line)
            _logger.info("➕ Tạo mới SOL %s: qty=%.2f", misa_data['code'], misa_data['qty'])
        
        # ===== XỬ LÝ SẢN PHẨM BỊ XÓA KHỎI MISA =====
        # KHÔNG xóa SOL, chỉ set qty = 0 để giữ lịch sử và cho Odoo xử lý
        
        for sol in unmatched_sols:
            code = sol.product_id.default_code or sol.product_id.name
            
            # Nếu đã có invoice posted -> giữ nguyên
            if posted_inv_exists:
                _logger.warning("⚠️ Dòng %s không còn trong MISA nhưng giữ nguyên (đã có invoice posted).", code)
                continue
            
            qty_delivered = float(getattr(sol, 'qty_delivered', 0.0) or 0.0)
            
            # Set qty = 0 hoặc qty_delivered (nếu đã giao)
            new_qty = max(qty_delivered, 0.0)
            try:
                sol.write({'product_uom_qty': new_qty})
                if new_qty > 0:
                    _logger.info("↘️ Set qty=%s cho dòng %s (đã giao %s, không xóa).", new_qty, code, qty_delivered)
                else:
                    _logger.info("↘️ Set qty=0 cho dòng %s (không còn trong MISA).", code)
            except Exception as e:
                _logger.warning("Không thể set qty cho dòng %s: %s", code, e)



    def _safe_unreserve_move(self, move):
        """Helper: Unreserve move một cách an toàn (reset qty_done, huỷ reserve)."""
        try:
            if move.move_line_ids:
                # reset mọi qty_done trên line (nếu có)
                move.move_line_ids.filtered(lambda ml: getattr(ml, 'qty_done', 0)).write({'qty_done': 0})
            if hasattr(move, '_do_unreserve'):
                move._do_unreserve()
            elif hasattr(move, 'do_unreserve'):
                move.do_unreserve()
        except Exception as exc:
            _logger.debug("Unreserve move %s failed: %s", move.id, exc)


    def _safe_cancel_move(self, move):
        """Helper: Cancel move an toàn; fallback về set qty=0 nếu không cancel được."""
        try:
            self._safe_unreserve_move(move)
            if move.state not in ('cancel', 'done'):
                if hasattr(move, '_action_cancel'):
                    move._action_cancel()
                else:
                    # một số bản dùng action_cancel()
                    move.action_cancel()
            _logger.debug("Cancelled move %s", move.id)
        except Exception as exc:
            _logger.warning("Cancel move %s failed: %s; fallback set qty=0", move.id, exc)
            try:
                move.write({'product_uom_qty': 0.0})
            except Exception as exc2:
                _logger.error("Fallback set qty=0 failed for move %s: %s", move.id, exc2)


    def _partial_resync_open_pickings_when_done_present(self, data, lines, headers):
        """
        Đồng bộ khi đã có ít nhất 1 picking 'done' (KHÔNG xoá/chạm picking done):
        - (Bước 0) Đưa SO lines về đúng MISA (nếu không có invoice 'posted')
        - (Bước 1) Tính đã giao (delivered) theo picking done
        - (Bước 2) Tính tổng theo MISA (misa_total) theo UoM mặc định
        - (Bước 3) Tính 'needed_in_open' = misa_total - delivered (min=0)
        - (Bước 4..7) Cập nhật/tạo/cancel các move ở picking mở theo needed_in_open
        Kết quả: tổng giao (done) + tổng ở picking mở = tổng theo MISA
        """
        self.ensure_one()
        env = self.env
        odoo_utils = env['odoo.utils']

        _logger.info("=== Bắt đầu partial resync cho SO %s ===", self.name)

        # --------- Cập nhật x_studio_misa_saler_code và x_studio_misa_order_date ---------
        misa_order_id = data.get("ID") or data.get("CustomID") or self.misa_id
        owner_date = {}
        try:
            owner_date = env['misa.api.utils'].get_saleorder_owner_and_date(misa_order_id, headers) or {}
        except Exception as _e:
            _logger.warning("Không lấy được OwnerIDText/SaleOrderDate cho SO=%s: %s", misa_order_id, _e)
        
        # Cập nhật các trường nếu có dữ liệu
        vals_header_upd = {}
        if owner_date.get('owner_code'):
            vals_header_upd['x_studio_misa_saler_code'] = owner_date['owner_code']
        if owner_date.get('sale_order_date'):
            vals_header_upd['x_studio_misa_order_date'] = owner_date['sale_order_date']
        if owner_date.get('misa_delivery'):
            vals_header_upd['x_studio_misa_delivery'] = owner_date['misa_delivery']
        if owner_date.get('httt'):
            vals_header_upd['x_studio_httt'] = owner_date['httt']
        if owner_date.get('htgh'):
            vals_header_upd['x_studio_htgh'] = owner_date['htgh']
        if owner_date.get('misa_note') and 'x_studio_misa_note' in env['sale.order']._fields:
            vals_header_upd['x_studio_misa_note'] = owner_date['misa_note']
        shipping_address_raw = (data.get('ShippingAddress') or '').strip()
        vals_header_upd['misa_shipping_address'] = shipping_address_raw or False
        vals_header_upd['x_studio_sdt_giao_hang'] = data.get('Phone') or False
        if vals_header_upd:
            self.write(vals_header_upd)
            _logger.info("✅ Đã cập nhật misa_saler_code/order_date/httt/htgh/misa_delivery cho SO %s", self.name)

        # --------- Cập nhật Địa chỉ Giao hàng (như action_resync_from_misa_hard) ---------
        try:
             # Danh sách e_accounts để xác định khách hàng TMĐT
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
                "KHÁCH HÀNG KHÔNG CUNG CẤP THÔNG TIN_SHOPEE DEWALT",
            }
            # Sử dụng helper để extract full address từ các trường thành phần
            shipping_addr = env['misa.api.utils'].extract_shipping_address_from_data(data) or ''
            partner_name  = data.get("AccountIDText") or data.get("BillingAccountIDText") or _("Khách hàng MISA")
            shipping_contact_name = owner_date.get('shipping_contact') or data.get("ShippingContactIDText")
            account_id = data.get("AccountID") or data.get("AccountId")
            partner = None
            misa_code = None
            tax_code = None
            if account_id:
                partner = env['misa.api.utils']._sync_customer_from_misa_account_api(account_id, headers)
                try:
                    ident = env['misa.api.utils'].get_account_identity(account_id, headers) or {}
                    misa_code = ident.get("account_number") or ident.get("id")
                    tax_code = ident.get("taxcode")
                except Exception as _e:
                    _logger.warning("Partial Resync: cannot get Account identity for AccountID=%s: %s", account_id, _e)
            if not partner:
                partner = odoo_utils._get_or_create_partner(
                    partner_name,
                    misa_code=misa_code,
                    tax_code=tax_code,
                )
            partner = partner.commercial_partner_id or partner

            delivery_contact = env['sale.api.import.wizard']._get_or_create_delivery_contact(
                parent_partner=partner,
                addr_str=shipping_addr,
                phone=data.get("Phone"),
                province_text=data.get("ShippingProvinceIDText") or data.get("BillingProvinceIDText"),
                contact_name=shipping_contact_name.strip() if shipping_contact_name else None,
                is_e_account=(partner_name in e_accounts)
            )
            
            if delivery_contact:
                self.write({
                    'partner_id': partner.id,
                    'partner_shipping_id': delivery_contact.id,
                    'partner_invoice_id': partner.id
                })
                open_pickings = self.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
                if open_pickings:
                    open_pickings.write({'partner_id': partner.id})
                _logger.info("✅ Partial Resync: Updated shipping/invoice address to %s", delivery_contact.display_name)
        except Exception as e_addr:
            _logger.warning("❌ Partial Resync: Failed to update address: %s", e_addr)

        # --------- Bước 0a: ĐỒNG BỘ TÊN SẢN PHẨM TỪ MISA ---------
        _logger.info("🔄 Đồng bộ tên sản phẩm từ MISA cho SO %s...", self.name)
        synced_count = 0
        for ln in (lines or []):
            # Bỏ qua combo child
            if ln.get("IsChildProduct"):
                continue
            
            product_code = (ln.get("ProductIDText") or "").strip()
            product_name = ln.get("Description") or product_code
            
            if product_code and product_name:
                result = odoo_utils._sync_product_name_from_misa(product_code, product_name)
                if result:
                    synced_count += 1
        
        if synced_count > 0:
            _logger.info("✅ Đã đồng bộ tên cho %d sản phẩm từ MISA", synced_count)

        # --------- Bước 0b: KIỂM TRA CÓ THAY ĐỔI THỰC SỰ KHÔNG ---------
        # Chỉ hủy phiếu pick nếu có thay đổi (thêm/xóa/sửa số lượng SP)
        # Để tránh hủy phiếu vô ích khi sync mà không có thay đổi gì
        
        def _flt_check(x, dv=0.0):
            try:
                return float(x or 0.0)
            except Exception:
                return dv
        
        # Build MISA product qty map (skip combo children)
        misa_qty_map = {}  # {product_code: total_qty}
        current_parent_code_check = None
        combo_codes_check = set()
        
        for ln in (lines or []):
            if ln.get("IsSetProduct"):
                combo_codes_check.add((ln.get("ProductIDText") or "").strip())
        
        for ln in (lines or []):
            code = (ln.get("ProductIDText") or "").strip()
            if not code:
                continue
            if ln.get("IsSetProduct"):
                current_parent_code_check = code
            if ln.get("IsChildProduct") and current_parent_code_check:
                # Skip children (same logic as in _sync_so_lines_from_misa_no_picking)
                continue
            qty = _flt_check(ln.get("Amount"), 0.0)
            misa_qty_map[code] = misa_qty_map.get(code, 0.0) + qty
        
        # Build current SO product qty map (for change detection only)
        so_qty_map = {}
        for sol in self.order_line:
            code = (sol.product_id.default_code or "").strip()
            if code:
                so_qty_map[code] = so_qty_map.get(code, 0.0) + sol.product_uom_qty
        
        # Compare: detect changes và phân loại
        has_new_products = False  # Có sản phẩm MỚI (code có trong MISA nhưng không có trong SO)
        has_qty_increase = False  # Có tăng số lượng
        has_qty_decrease = False  # Có giảm số lượng
        
        all_codes = set(misa_qty_map.keys()) | set(so_qty_map.keys())
        
        for code in all_codes:
            misa_qty = misa_qty_map.get(code, 0.0)
            so_qty = so_qty_map.get(code, 0.0)
            
            # Sản phẩm MỚI: có trong MISA nhưng KHÔNG có trong SO
            if code in misa_qty_map and code not in so_qty_map:
                has_new_products = True
                _logger.info("📦 Phát hiện SP MỚI: %s (qty: %s)", code, misa_qty)
            elif abs(misa_qty - so_qty) > 0.001:
                if misa_qty > so_qty:
                    has_qty_increase = True
                    _logger.info("📈 Phát hiện TĂNG qty: %s (SO: %s → MISA: %s)", code, so_qty, misa_qty)
                else:
                    has_qty_decrease = True
                    _logger.info("📉 Phát hiện GIẢM qty: %s (SO: %s → MISA: %s)", code, so_qty, misa_qty)
        
        has_changes = has_new_products or has_qty_increase or has_qty_decrease
        
        if not has_changes:
            _logger.info("ℹ️ Không có thay đổi SO lines → giữ nguyên")
        
        # ===== KHÔNG HỦY PHIẾU - ĐỂ ODOO XỬ LÝ MẶC ĐỊNH =====
        # Chỉ log thay đổi, để Odoo tự xử lý việc tạo/cập nhật picking
        if has_changes:
            _logger.info("📊 Phát hiện thay đổi: new_products=%s, qty_increase=%s, qty_decrease=%s",
                        has_new_products, has_qty_increase, has_qty_decrease)
            _logger.info("ℹ️ Để Odoo xử lý mặc định (KHÔNG hủy phiếu)")
            
            # Tạo thông báo cho kho biết có thay đổi từ MISA
            change_details = []
            if has_new_products:
                change_details.append("• Có sản phẩm MỚI được thêm")
            if has_qty_increase:
                change_details.append("• Số lượng được TĂNG")
            if has_qty_decrease:
                change_details.append("• Số lượng được GIẢM")
            
            change_msg = Markup(_(
                "<div style='color: orange; font-weight: bold;'>⚠️ THÔNG BÁO: ĐƠN HÀNG CÓ THAY ĐỔI TỪ MISA</div><br/>"
                "<b>Chi tiết thay đổi:</b><br/>%s<br/><br/>"
                "<i>Vui lòng kiểm tra lại các phiếu kho và thực hiện điều chỉnh nếu cần.</i>"
            )) % Markup("<br/>".join(change_details))
            self.message_post(body=change_msg)
        
        # --------- Bước 0c: đưa dòng SO về đúng MISA (nếu không có invoice posted) ---------
        # Sync SO lines và để Odoo xử lý tự động
        if self.invoice_ids.filtered(lambda inv: inv.state == 'posted'):
            _logger.warning("Bỏ qua cập nhật SO lines vì có hoá đơn 'posted'. Sẽ chỉ vá picking mở.")
        else:
            try:
                self._sync_so_lines_from_misa_no_picking(lines, headers)
            except Exception as exc:
                # Re-raise UserError để hiện thông báo cho user
                if 'UserError' in type(exc).__name__:
                    raise
                _logger.warning("Không thể đồng bộ SO lines: %s (tiếp tục vá picking)", exc)

        # --------- Bước 1: tổng đã giao theo sale.order.line.qty_delivered ----------
        # LƯU Ý: Trong flow đi 3 phiếu (pick/pack/out), không thể tính tổng qty_done của các move_line
        # vì sẽ bị đếm trùng 3 lần. Phải dùng trường qty_delivered trên sale.order.line
        # (Odoo đã tự động tính field này từ stock.move done cuối cùng)
        delivered_by_product = {}
        _logger.info("Tính tổng đã giao từ sale.order.line.qty_delivered")

        for line in self.order_line:
            prod = line.product_id
            if not prod or prod.type == 'service':
                continue
            
            # Dùng qty_delivered field (đã được Odoo compute từ stock moves)
            # Trường này đã xử lý đúng cho cả flow 1/2/3 step delivery
            qty_delivered = float(line.qty_delivered or 0.0)
            
            # Group theo product: cộng dồn nếu cùng sản phẩm xuất hiện ở nhiều dòng
            delivered_by_product[prod] = delivered_by_product.get(prod, 0.0) + qty_delivered
            _logger.debug("    Delivered %s: +%.2f (tổng=%.2f)",
                        prod.display_name, qty_delivered, delivered_by_product[prod])

        # --------- Bước 2: tổng theo MISA (quy về UoM mặc định) ----------
        def _flt(x, dv=0.0):
            try:
                return float(x or 0.0)
            except Exception:
                return dv

        # Build combo_codes_with_bom: combo parent có phantom BOM → Odoo tự explode via BOM Kit
        # → SKIP children khỏi misa_total (nếu tính children thì delivered=0 → needed > 0 → trigger
        #   procurement thừa, hoặc code cũ sẽ tạo manual moves bypass BOM explosion)
        combo_codes_with_bom_step2 = set()
        for ln in (lines or []):
            if ln.get("IsSetProduct"):
                combo_code = (ln.get("ProductIDText") or "").strip()
                if combo_code:
                    prod_check = env['product.product'].search([('default_code', '=', combo_code)], limit=1)
                    if prod_check and env['mrp.bom'].search_count([
                        ('product_tmpl_id', '=', prod_check.product_tmpl_id.id),
                        ('type', '=', 'phantom'),
                        ('active', '=', True),
                    ]) > 0:
                        combo_codes_with_bom_step2.add(combo_code)

        misa_total_by_product = {}
        current_parent_code_step2 = None
        for ln in (lines or []):
            product_code = ln.get("ProductIDText")
            if not product_code:
                continue

            if ln.get("IsSetProduct"):
                current_parent_code_step2 = product_code

            # Skip combo children nếu parent có phantom BOM — delivery tracking qua parent SOL
            if ln.get("IsChildProduct"):
                if current_parent_code_step2 and current_parent_code_step2 in combo_codes_with_bom_step2:
                    _logger.debug("Step2: skip child '%s' (parent '%s' có BoM Kit)", product_code, current_parent_code_step2)
                    continue

            desc     = ln.get("Description") or product_code
            qty      = _flt(ln.get("Amount"), 0.0)
            price    = _flt(ln.get("Price"), 0.0)
            uom_name = (ln.get("UnitIDText") or "Cái").strip()
            misa_pid = ln.get("ProductID") or ln.get("ProductId")

            product = odoo_utils._get_or_create_product(
                code=product_code,
                name=desc,
                unit_name=uom_name,
                cost=price,
                product_type="consu",
                purchase_ok=True,
                sale_ok=True,
            )

            qty_base, price_dummy, is_default = self._convert_qty_price_to_default_uom(
                product=product,
                misa_uom_text=uom_name,
                qty=qty,
                price=price,
                misa_product_id=misa_pid,
                headers=headers,
            )
            misa_total_by_product[product] = misa_total_by_product.get(product, 0.0) + (qty_base or 0.0)
            _logger.debug("MISA Total %s: %s", product.display_name, misa_total_by_product[product])

        # --------- Bước 3 (VIẾT LẠI): Kiểm tra over-delivery & tính 'needed_in_open' ----------
        # Mục tiêu: Nếu đã giao (delivered) > tổng theo MISA (misa_total) cho bất kỳ sản phẩm nào
        # => CHẶN ĐỒNG BỘ NGAY (raise UserError). Không tiếp tục các bước sau.
        needed_in_open_by_product = {}
        over_deliveries = []
        EPS = 1e-9  # chống sai số float nhỏ

        # Hợp tất cả sản phẩm xuất hiện ở MISA hoặc đã giao
        all_products = set(list(misa_total_by_product.keys()) + list(delivered_by_product.keys()))

        for prod in all_products:
            misa_total = float(misa_total_by_product.get(prod, 0.0) or 0.0)
            delivered  = float(delivered_by_product.get(prod, 0.0) or 0.0)

            if delivered > misa_total + EPS:
                # Ghi nhận vi phạm over-delivery (đã giao vượt số MISA)
                over_deliveries.append((prod, misa_total, delivered))
                _logger.error(
                    "Over-delivery: %s | MISA_total=%s, delivered=%s",
                    prod.display_name, misa_total, delivered
                )
            else:
                # Không vi phạm: tính phần còn thiếu để đẩy vào picking mở
                needed = misa_total - delivered
                # needed luôn >= 0 do đã loại trường hợp delivered > misa_total
                needed_in_open_by_product[prod] = needed
                _logger.info(
                    "Need in open %s: MISA_total=%s, delivered=%s, needed_in_open=%s",
                    prod.display_name, misa_total, delivered, needed
                )

        # Nếu có bất kỳ sản phẩm nào over-delivery => chặn đồng bộ
        if over_deliveries:
            details = "\n".join(
                f"- {p.display_name}: MISA={m:g}, Đã giao={d:g}"
                for (p, m, d) in over_deliveries
            )
            _logger.error("CHẶN ĐỒNG BỘ do over-delivery:\n%s", details)
            raise UserError(_(
                "Phát hiện đã giao vượt số lượng theo MISA, đồng bộ bị chặn.\n"
                "%s\n\n"
                "Vui lòng xử lý nghiệp vụ trước khi đồng bộ lại:\n"
                "• Tạo phiếu trả hàng / điều chỉnh kho để đưa 'đã giao' ≤ số trên MISA.\n"
                "• Hoặc cập nhật lại số lượng trên MISA nếu MISA mới là số chuẩn."
            ) % details)
        # --------- Bước 4: Để Odoo tự quản lý picking ----------
        # KHÔNG tạo picking/move thủ công nữa.
        # SO lines đã được đồng bộ ở bước trước → Odoo sẽ tự tạo/cập nhật picking
        # qua cơ chế procurement rules khi thay đổi qty trên SO lines.
        
        # Nếu có sản phẩm cần giao thêm, thử force re-confirm để trigger picking
        nothing_to_ship = all(qty <= 0.0 for qty in needed_in_open_by_product.values())
        
        if not nothing_to_ship:
            # Có sản phẩm cần giao → trigger procurement
            _logger.info("Còn sản phẩm cần giao → trigger Odoo procurement")
            try:
                # Nếu SO đang draft/sent thì confirm
                if self.state in ('draft', 'sent'):
                    self.action_confirm()
                
                # Trigger lại procurement cho các line chưa giao đủ
                for line in self.order_line:
                    if line.product_id.type != 'service':
                        qty_to_deliver = line.product_uom_qty - line.qty_delivered
                        if qty_to_deliver > 0.001:
                            # Gọi _action_launch_stock_rule nếu có
                            if hasattr(line, '_action_launch_stock_rule'):
                                try:
                                    line._action_launch_stock_rule()
                                    _logger.info("Triggered stock rule for %s (qty=%s)", 
                                               line.product_id.display_name, qty_to_deliver)
                                except Exception as e:
                                    _logger.warning("Trigger stock rule lỗi cho %s: %s", 
                                                  line.product_id.display_name, e)
            except Exception as e:
                _logger.warning("Không thể trigger procurement: %s", e)
        
        # --------- Bước 5: Thông báo kết quả ----------
        summary_parts = []
        for prod, needed in needed_in_open_by_product.items():
            if needed > 0:
                summary_parts.append(f"{prod.display_name}: {needed:g}")

        summary = _("Đã đồng bộ SO lines. Odoo sẽ tự tạo picking cho: %s") % (
            ", ".join(summary_parts) if summary_parts else _("không có gì thêm")
        )
        _logger.info("Kết quả đồng bộ SO %s: %s", self.name, summary)
        self.message_post(body=_("Đồng bộ MISA thành công. %s") % summary)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Đồng bộ thành công"),
                'message': summary,
                'type': 'success'
            }
        }


    def action_update_tag_single(self):
        """Action to update tags based on address for a single order."""
        self.ensure_one()
        misa_utils = self.env['misa.api.utils']
        addr = self.partner_shipping_id.street or self.partner_id.street
        if addr:
            tag_ids = misa_utils.map_address_to_tag_ids(self.env, addr)
            if tag_ids:
                self.write({'tag_ids': tag_ids})
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("Cập nhật thành công"),
                        'message': _("Đã cập nhật Tag cho đơn hàng."),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("Không tìm thấy"),
                        'message': _("Không tìm thấy Tag phù hợp cho địa chỉ này."),
                        'type': 'warning',
                        'sticky': False,
                    }
                }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Lỗi"),
                    'message': _("Đơn hàng không có địa chỉ giao hàng."),
                    'type': 'danger',
                    'sticky': False,
                }
            }

    def _auto_apply_misa_tags(self):
        """
        Duyệt qua các order trong self, lấy địa chỉ và gọi
        misa.api.utils để tìm tag phù hợp, sau đó write vào đơn hàng.
        """
        # Khởi tạo model utils
        misa_utils = self.env['misa.api.utils']
        
        for order in self:
            # Lấy địa chỉ giao hàng hoặc địa chỉ xuất hóa đơn
            addr = order.partner_shipping_id.street or order.partner_id.street
            
            if addr:
                # Gọi hàm map bên model utils (theo code mẫu bạn cung cấp)
                # Lưu ý: map_address_to_tag_ids trả về dạng [(6, 0, [ids])]
                tag_ids = misa_utils.map_address_to_tag_ids(self.env, addr)
                
                if tag_ids:
                    order.write({'tag_ids': tag_ids})
    # api gắn tag@api.model
    def create(self, vals):
        # Gọi super để tạo đơn hàng như bình thường
        record = super(SaleOrder, self).create(vals)
        
        # --- CHÈN LOGIC GẮN TAG Ở ĐÂY ---
        # Tự động gắn tag ngay sau khi tạo xong
        # Lưu ý: Hàm này sẽ chạy cho cả tạo tay và tạo qua API cơ bản
        if not record.tag_ids:
            record._auto_apply_misa_tags()
        # --------------------------------
            
        return record
# =====================API
    @api.model
    def api_resync_by_misa(self, misa_order_id, warehouse_id=None, create_when_missing=True):
        """
        Public API (RPC/JSON-RPC) để resync đơn bán theo MISA Order ID.
        - Nếu tìm thấy SO có misa_id => gọi action_resync_from_misa_hard() trên record đó.
        - Nếu không thấy và create_when_missing=True => tạo 1 SO bootstrap (tối thiểu) với misa_id rồi gọi resync.
        Trả về: dict {'ok': bool, 'res_id': int or None, 'name': str or None, 'detail': str or None}
        """
        misa_order_id = (str(misa_order_id or '')).strip()
        if not misa_order_id:
            raise UserError(_("Thiếu misa_order_id"))
        # 1) Tìm SO hiện hữu theo misa_id
        so = self.search([('misa_id', '=', misa_order_id)], limit=1)
        if so:
            # Gọi hàm "hard resync" sẵn có
            action = so.sudo().action_resync_from_misa_hard()
            # action thường là ir.actions.act_window có res_id là SO mới
            res_id = action.get('res_id') if isinstance(action, dict) else so.id
            so_new = self.browse(res_id)
            return {
                'ok': True,
                'res_id': so_new.id,
                'name': so_new.name,
                'detail': 'resynced_existing',
            }
        # 2) Không thấy → tạo SO bootstrap (nếu cho phép)
        if not create_when_missing:
            return {'ok': False, 'res_id': None, 'name': None, 'detail': 'not_found'}
        # Chọn partner tối thiểu (public_partner nếu có)
        try:
            partner = self.env.ref('base.public_partner')
        except Exception:
            partner = self.env['res.partner'].search([], limit=1)
        if not partner:
            raise UserError(_("Không tìm thấy đối tác mặc định để bootstrap đơn."))
        vals = {
            'name': f"TMP-MISA-{misa_order_id}",
            'partner_id': partner.id,
            'misa_id': misa_order_id,
        }
        if warehouse_id:
            vals['warehouse_id'] = int(warehouse_id)
            
        so_boot = self.create(vals)
        # Gọi lại resync cứng trên record bootstrap (hàm của bạn sẽ tự huỷ & tạo mới theo MISA)
        action = so_boot.sudo().action_resync_from_misa_hard()
        res_id = action.get('res_id') if isinstance(action, dict) else so_boot.id
        so_new = self.browse(res_id)
        
        if so_new:
            so_new._auto_apply_misa_tags()
        return {
            'ok': True,
            'res_id': so_new.id,
            'name': so_new.name,
            'detail': 'created_then_resynced',
        }


