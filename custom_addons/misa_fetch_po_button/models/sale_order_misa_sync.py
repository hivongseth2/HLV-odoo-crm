# models/sale_order_misa_sync.py
import requests
import logging
import pytz
from odoo import models, fields, api, _
from markupsafe import Markup
from dateutil.parser import parse as dtparse
from odoo.exceptions import UserError
import json

_logger = logging.getLogger(__name__)
MISA_CRM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
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
        crm_token = misa_utils._fetch_login_crm_token_cached()
        return misa_config.get_crm_header(crm_token), crm_token

    def _misa_fetch_order(self, headers=None):
        """Gọi FormDataNew lấy thông tin chung 1 đơn."""
        self.ensure_one()
        if not self.misa_id:
            raise ValueError(_("Thiếu MISA ID trên đơn bán."))

        if headers is None:
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
        
        if not js.get("Success"):
            raise ValueError(_("MISA trả về lỗi (FormDataNew): %s") % js)
        return js.get("Data", {}).get("CurrentData", {})

    @api.model
    def _misa_fetch_lines(self, misa_order_id, headers=None):
        """Gọi DataSubPaging lấy các dòng sản phẩm (theo cách bạn đang dùng)."""
        misa_utils = self.env['misa.api.utils']
        misa_config = self.env['misa.config']
        if headers is None:
            headers, _crm_token = self._misa_headers()

        # bạn đã có sẵn helper get_crm_sale_order_detail_payload + get_list_product_by_order_crm
        order_detail_url = "https://amisapp.misa.vn/crm/g2/api/business/SaleOrder/DataSubPaging"
        payload_detail = misa_config.get_crm_sale_order_detail_payload(misa_order_id)
        product_lines = misa_utils.get_list_product_by_order_crm(order_detail_url, headers, payload_detail)
        # logging.debug("productline", product_lines)
        return product_lines or []

    @api.model
    def _misa_warehouse_from_sale_lines(self, lines):
        """Xác định kho Odoo từ dòng SO MISA đầu tiên có mã kho map được."""
        stock_mapping = {
            "HCM": "TSN/Stock",
            "BENCAM": "KBC/Tồn kho",
            "HIENDUC": "KHD/Tồn kho",
            "HCM_SHOWROOM": "TSNSR/Stock",
            "HLV": "TSN/Stock",
            "BẾN CAM": "KBC/Tồn kho",
            "BẾNCAM": "KBC/Tồn kho",
            "HIỀN ĐỨC": "KHD/Tồn kho",
            "ĐÀ NẴNG": "KDN/Tồn kho",
            "ĐÀNẴNG": "KDN/Tồn kho",
            "HIỀNĐỨC": "KHD/Tồn kho",
            "DANANG": "KDN/Tồn kho",
            "TSN SHOWROOM": "TSNSR/Stock",
            "TSNSHOWROOM": "TSNSR/Stock",
            "TSNSR": "TSNSR/Stock",
        }

        for line in lines or []:
            # Luồng cũ lưu mã kho ở CustomField2; một số response trả đúng StockIDText.
            candidates = (line.get("CustomField2"), line.get("StockIDText"))
            _logger.info(
                "🏭 Warehouse candidates MISA line ID=%s product=%s: "
                "CustomField2=%r, StockID=%r, StockIDText=%r, candidates=%r",
                line.get("ID") or line.get("id"),
                line.get("ProductIDText"),
                line.get("CustomField2"),
                line.get("StockID"),
                line.get("StockIDText"),
                candidates,
            )
            for raw_stock_id in candidates:
                stock_id = str(raw_stock_id or "").strip().upper()
                if not stock_id:
                    continue

                location_name = stock_mapping.get(stock_id)
                if not location_name:
                    _logger.info("🏭 Bỏ qua mã kho MISA chưa có mapping: %s", stock_id)
                    continue

                location = self.env['stock.location'].search([
                    ('complete_name', '=', location_name),
                ], limit=1)
                if not location:
                    _logger.warning(
                        "⚠️ Không tìm thấy stock.location %s cho mã kho MISA %s",
                        location_name, stock_id,
                    )
                    continue

                warehouse = (
                    location.warehouse_id
                    if 'warehouse_id' in location._fields
                    else False
                )
                if not warehouse and location.location_id:
                    warehouse = self.env['stock.warehouse'].search([
                        ('view_location_id', '=', location.location_id.id),
                    ], limit=1)
                if not warehouse:
                    _logger.warning(
                        "⚠️ Không tìm thấy stock.warehouse từ location %s",
                        location.complete_name,
                    )
                    continue

                _logger.info(
                    "🏭 Xác định kho SO từ dòng MISA: %s → %s",
                    stock_id, warehouse.name,
                )
                return warehouse

        _logger.warning("⚠️ Không xác định được kho từ SO line MISA; giữ kho mặc định Odoo")
        return self.env['stock.warehouse']
        # ===== Helpers lấy/convert UoM từ MISA =====

    
    def _misa_fetch_conversion_units(self, product_id, headers, cache=None):
        """
        Gọi Product/DataSubPaging để lấy quy đổi UoM cho 1 sản phẩm (payload theo yêu cầu của bạn).
        """
        if not product_id:
            _logger.warning(
                "MISA SO UoM conversions: missing product_id, skip DataSubPaging"
            )
            return []
        cache_key = str(product_id)
        if cache is not None and cache_key in cache:
            _logger.warning(
                "MISA SO UoM conversions cache hit: product_id=%r conversions=%s",
                product_id,
                cache[cache_key],
            )
            return cache[cache_key]
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
            _logger.warning(
                "MISA SO UoM conversions fetch: product_id=%r table=product_conversion_unit",
                product_id,
            )
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            result = data.get("Data", []) or []
            _logger.warning(
                "MISA SO UoM conversions fetched: product_id=%r count=%s conversions=%s",
                product_id,
                len(result),
                result,
            )
            if cache is not None:
                cache[cache_key] = result
            return result
        except Exception as e:
            _logger.exception("❗ Lỗi gọi Product/DataSubPaging: %s", e)
            return []

    def _convert_qty_price_to_default_uom(
        self, product, misa_uom_text, qty, price, misa_product_id, headers,
        conversion_cache=None,
    ):
        """
        Chuyển qty/price từ đơn vị lấy từ MISA (misa_uom_text) về đơn vị mặc định của product (product.uom_id).
        Trả về: (qty_base, price_base, uom_is_default)
        - uom_is_default = True nếu misa_uom_text trùng default (không cần convert)
        """
        default_uom_name = (product.uom_id and product.uom_id.name) or ""
        _logger.warning(
            "MISA SO UoM conversion check: product_code=%r product_id=%r "
            "requested_uom=%r default_uom=%r",
            product.default_code,
            misa_product_id,
            misa_uom_text,
            default_uom_name,
        )
        if not misa_uom_text or misa_uom_text.strip().lower() == default_uom_name.strip().lower():
            _logger.warning(
                "MISA SO UoM conversion skip: requested UoM already matches default UoM"
            )
            return qty, price, True  # không cần đổi

        # Lấy bảng quy đổi theo ProductID
        if not misa_product_id:
            _logger.warning(
                "MISA SO UoM conversion skip fetch: product_code=%r has no MISA ProductID",
                product.default_code,
            )
        conversions = (
            self._misa_fetch_conversion_units(
                misa_product_id,
                headers,
                cache=conversion_cache,
            )
            if misa_product_id else []
        )
        _logger.warning(
            "MISA SO UoM conversion lookup: product_code=%r product_id=%r "
            "requested_uom=%r default_uom=%r candidates=%r",
            product.default_code,
            misa_product_id,
            misa_uom_text,
            default_uom_name,
            [
                c.get("ConversionUnitIDText")
                for c in (conversions or [])
            ],
        )
        requested_uom_key = misa_uom_text.strip().lower()
        default_uom_key = default_uom_name.strip().lower()

        # Normal direction: the MISA line uses a conversion unit and Odoo uses
        # the MISA base unit. Example: line=Box, default=Piece.
        conv = next((
            c for c in (conversions or [])
            if (c.get("ConversionUnitIDText") or "").strip().lower() == requested_uom_key
        ), None)
        reverse_conversion = False

        # Reverse direction: the MISA line uses the base unit while Odoo uses
        # a conversion unit. Example: line=Piece, default=Bag and
        # "1 Bag = 100 Pieces".
        if not conv:
            conv = next((
                c for c in (conversions or [])
                if (c.get("ConversionUnitIDText") or "").strip().lower() == default_uom_key
            ), None)
            reverse_conversion = bool(conv)

        if not conv:
            _logger.warning(
                "⚠️ Không tìm thấy mapping UoM cho '%s' -> '%s' "
                "-> giữ nguyên số liệu gốc",
                misa_uom_text,
                default_uom_name,
            )
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
        if reverse_conversion:
            if op_id == 1:
                qty_base = qty / rate
                price_base = price * rate
            else:
                qty_base = qty * rate
                price_base = price / rate
        elif op_id == 1:
            qty_base = qty * rate
            price_base = price / rate
        else:  # op_id == 2 (Chia) hoặc bất kỳ khác coi như "Chia"
            qty_base = qty / rate
            price_base = price * rate

        _logger.warning(
            "MISA SO UoM converted: product_code=%r direction=%s "
            "%s %s @ %s -> %s %s @ %s (rate=%s operator=%s)",
            product.default_code,
            "base_to_conversion" if reverse_conversion else "conversion_to_base",
            qty,
            misa_uom_text,
            price,
            qty_base,
            default_uom_name,
            price_base,
            rate,
            op_id,
        )

        return qty_base, price_base, False


    # ---------------- core sync ----------------

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


    def _sync_so_lines_from_misa_no_picking(
        self, lines, headers, defer_quantity=False, prepared_lines=None,
    ):
        """
        Đưa các dòng SO về đúng như MISA (qty/price/uom) theo UoM mặc định của product.
        KHÔNG group theo product code - mỗi dòng MISA = 1 SOL riêng biệt.
        KHÔNG đụng pickings. Nếu có hoá đơn 'posted' thì KHÔNG nên gọi hàm này.
        """
        self.ensure_one()
        env = self.env
        odoo_utils = env['odoo.utils']
        SaleLine = env['sale.order.line']
        source_lines = [] if prepared_lines is not None else (lines or [])
        conversion_cache = {}

        def _flt(x, dv=0.0):
            try:
                return float(x or 0.0)
            except Exception:
                return dv

        # ===== Build combo_codes_with_bom để skip children =====
        # Nếu combo parent có BoM Kit, Odoo sẽ tự explode ra picking
        # → không cần thêm children vào SO, tránh trùng lặp
        combo_codes_with_bom = set()
        for ln in source_lines:
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
        
        for ln in source_lines:
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
            loyalty_discount_present = "CustomField10" in ln
            loyalty_discount_pct = _flt(ln.get("CustomField10"), 0.0)
            uom_name   = (ln.get("UnitIDText") or "Cái").strip()
            misa_pid   = ln.get("ProductID") or ln.get("ProductId")
            note_text  = (ln.get("DescriptionProduct") or ln.get("Note") or "")
            x_studio_product_status = (ln.get("CustomField4") or "").strip()

            _logger.info(
                "🎯 MISA SO line ID=%s product=%s: "
                "has_CustomField10=%s, CustomField10=%r "
                "→ loyalty_discount_pct=%s",
                ln.get("ID"),
                code or misa_pid,
                loyalty_discount_present,
                ln.get("CustomField10"),
                loyalty_discount_pct,
            )

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
                conversion_cache=conversion_cache,
            )

            tax_ids = self._tax_ids_from_misa_line(ln)
            
            misa_sol_data.append({
                'crm_line_id': str(ln.get('ID') or '').strip(),
                'product': product,
                'code': code,
                'name': desc,
                'qty': qty_base,
                'price': price_base,
                'discount': discount,
                'loyalty_discount_present': loyalty_discount_present,
                'loyalty_discount_pct': loyalty_discount_pct,
                'note': note_text,
                'tax_ids': tax_ids,
                'is_default_uom': is_default,
                'status': x_studio_product_status,
                'crm_qty': qty,
                'crm_price': price,
                'crm_discount': discount,
                'crm_uom': uom_name,
            })

        # Khi kho duyệt, dùng dữ liệu đã chuẩn hóa/lưu từ lần fetch trước.
        # Không gọi lại CRM, kể cả API quy đổi đơn vị sản phẩm.
        if prepared_lines is not None:
            Product = env['product.product']
            for saved in prepared_lines:
                product = Product.browse(int(saved.get('product_id') or 0)).exists()
                if not product:
                    raise UserError(_(
                        "Sản phẩm của snapshot MISA không còn tồn tại trong Odoo (CRM line %s)."
                    ) % (saved.get('crm_line_id') or '-'))
                misa_sol_data.append({
                    'crm_line_id': str(saved.get('crm_line_id') or '').strip(),
                    'product': product,
                    'code': saved.get('code') or product.default_code or product.display_name,
                    'name': saved.get('name') or product.display_name,
                    'qty': float(saved.get('qty') or 0.0),
                    'price': float(saved.get('price') or 0.0),
                    'discount': float(saved.get('discount') or 0.0),
                    'loyalty_discount_present': bool(saved.get(
                        'loyalty_discount_present',
                        'loyalty_discount_pct' in saved,
                    )),
                    'loyalty_discount_pct': float(
                        saved.get('loyalty_discount_pct') or 0.0
                    ),
                    'note': saved.get('note') or '',
                    'tax_ids': [int(tax_id) for tax_id in (saved.get('tax_ids') or [])],
                    'is_default_uom': bool(saved.get('is_default_uom')),
                    'status': saved.get('status') or '',
                    'crm_qty': float(saved.get('crm_qty', saved.get('qty')) or 0.0),
                    'crm_price': float(saved.get('crm_price', saved.get('price')) or 0.0),
                    'crm_discount': float(saved.get('crm_discount', saved.get('discount')) or 0.0),
                    'crm_uom': saved.get('crm_uom') or '',
                })

        line_snapshot = [{
            'crm_line_id': item['crm_line_id'],
            'product_id': item['product'].id,
            'code': item['code'],
            'name': item['name'],
            'qty': item['qty'],
            'price': item['price'],
            'discount': item['discount'],
            'loyalty_discount_present': item['loyalty_discount_present'],
            'loyalty_discount_pct': item['loyalty_discount_pct'],
            'note': item['note'],
            'tax_ids': item['tax_ids'],
            'is_default_uom': item['is_default_uom'],
            'status': item['status'],
            'crm_qty': item['crm_qty'],
            'crm_price': item['crm_price'],
            'crm_discount': item['crm_discount'],
            'crm_uom': item['crm_uom'],
        } for item in misa_sol_data]

        # Lấy danh sách SOL hiện tại
        existing_sols = list(self.order_line.filtered(lambda line: not line.display_type))
        qty_changes = []
        audit_changes = []
        approved_legacy_removal_ids = {
            int(line_id)
            for line_id in (
                self.env.context.get('misa_approved_legacy_removal_line_ids') or []
            )
        }
        has_sync_history = bool(self.misa_sync_snapshot_ids)

        def _is_removed_misa_line(sol):
            """Nhận diện cả dòng legacy của đơn chưa từng có snapshot MISA."""
            return bool(
                sol.misa_crm_line_id
                or not has_sync_history
                or sol.id in approved_legacy_removal_ids
            )

        def _audit(misa_data, sol, field_name, old_value, new_value, change_type='update'):
            change = {
                'change_type': change_type,
                'crm_line_id': misa_data.get('crm_line_id') if misa_data else sol.misa_crm_line_id,
                'sale_order_line_id': sol.id if sol else False,
                'product_id': (
                    misa_data['product'].id if misa_data and misa_data.get('product')
                    else sol.product_id.id
                ),
                'product_code': (
                    misa_data.get('code') if misa_data
                    else sol.product_id.default_code or sol.product_id.display_name
                ),
                'field_name': field_name,
                'old_value': str(old_value if old_value not in (None, False) else ''),
                'new_value': str(new_value if new_value not in (None, False) else ''),
            }
            audit_changes.append(change)
            return change
        
        # Match: Tìm SOL hiện có khớp với từng dòng MISA
        # Ưu tiên match theo: product + qty + price (tránh nhầm lẫn khi có 2 dòng cùng product)
        matched_pairs = []  # [(misa_data, sol)]
        unmatched_misa = list(misa_sol_data)
        unmatched_sols = list(existing_sols)
        
        # Pass 0: CRM line ID là khóa chính, kể cả khi một SKU xuất hiện nhiều dòng.
        existing_by_crm_id = {
            sol.misa_crm_line_id: sol
            for sol in unmatched_sols
            if sol.misa_crm_line_id
        }
        for misa_data in list(unmatched_misa):
            crm_line_id = misa_data['crm_line_id']
            sol = existing_by_crm_id.get(crm_line_id) if crm_line_id else None
            if sol and sol in unmatched_sols:
                matched_pairs.append((misa_data, sol))
                unmatched_misa.remove(misa_data)
                unmatched_sols.remove(sol)

        # Pass 1: migration cho dòng cũ chưa có CRM line ID.
        for misa_data in list(unmatched_misa):
            for sol in list(unmatched_sols):
                if (not sol.misa_crm_line_id
                    and sol.product_id == misa_data['product']
                    and abs(sol.product_uom_qty - misa_data['qty']) < 0.01
                    and abs(sol.price_unit - misa_data['price']) < 0.01):
                    matched_pairs.append((misa_data, sol))
                    unmatched_misa.remove(misa_data)
                    unmatched_sols.remove(sol)
                    break
        
        # Pass 2: Match theo product (cho các dòng còn lại)
        for misa_data in list(unmatched_misa):
            for sol in list(unmatched_sols):
                if not sol.misa_crm_line_id and sol.product_id == misa_data['product']:
                    matched_pairs.append((misa_data, sol))
                    unmatched_misa.remove(misa_data)
                    unmatched_sols.remove(sol)
                    break
        
        
        # Không cho dữ liệu CRM ghi đè số lượng đặt hàng xuống thấp hơn số đã
        # giao thực tế. Kiểm tra toàn bộ trước khi write để tránh đồng bộ dở dang.
        invalid_delivered_quantities = []
        for misa_data, sol in matched_pairs:
            qty_delivered = float(getattr(sol, 'qty_delivered', 0.0) or 0.0)
            new_qty = float(misa_data['qty'] or 0.0)

            if new_qty < qty_delivered - 0.001:  # Cho phép sai số nhỏ
                invalid_delivered_quantities.append(
                    _("%(code)s: số lượng MISA %(new_qty)g < đã giao %(delivered_qty)g "
                      "(CRM line %(crm_line_id)s)") % {
                        'code': misa_data['code'],
                        'new_qty': new_qty,
                        'delivered_qty': qty_delivered,
                        'crm_line_id': misa_data['crm_line_id'] or '-',
                    }
                )

        # Một dòng đã giao nhưng bị xóa khỏi CRM tương đương yêu cầu giảm về 0.
        for sol in unmatched_sols:
            if not _is_removed_misa_line(sol):
                continue
            qty_delivered = float(getattr(sol, 'qty_delivered', 0.0) or 0.0)
            if qty_delivered > 0.001:
                invalid_delivered_quantities.append(
                    _("%(code)s: dòng đã bị xóa khỏi MISA nhưng đã giao %(delivered_qty)g "
                      "(CRM line %(crm_line_id)s)") % {
                        'code': sol.product_id.default_code or sol.product_id.display_name,
                        'delivered_qty': qty_delivered,
                        'crm_line_id': sol.misa_crm_line_id or _('legacy/chưa có lịch sử'),
                    }
                )

        if invalid_delivered_quantities:
            raise UserError(_(
                "Không thể đồng bộ vì số lượng MISA thấp hơn số lượng đã giao:\n- %(details)s\n\n"
                "Hãy đặt số lượng MISA tối thiểu bằng số đã giao. Nếu khách trả hàng, "
                "hãy xử lý phiếu trả kho trước rồi đồng bộ lại."
            ) % {
                'details': '\n- '.join(invalid_delivered_quantities),
            })

        # Odoo core chặn write product_id lên order line khi
        # sale.order.line.product_updatable = False. Field này bị False vì: (1) đơn đã
        # khóa, (2) dòng đã xuất hóa đơn, (3) dòng đã giao hàng thật, hoặc (4, do
        # sale_stock) dòng còn phiếu giao (stock.move) chưa done/cancel — dù chưa giao gì
        # cả, đây chỉ là phiếu treo tham chiếu sản phẩm cũ từ lúc xác nhận đơn.
        # - Case (1) đơn khóa nhưng chưa tác động gì khác: mở khóa tạm để ghi, khóa lại
        #   ở cuối hàm.
        # - Case (4) chưa có tác động kho thật: tự hủy phiếu treo đó rồi cho ghi tiếp;
        #   Odoo sẽ tự tạo phiếu giao mới đúng sản phẩm khi write product_uom_qty
        #   (sale_stock.SaleOrderLine.write gọi _action_launch_stock_rule).
        # - Case (2)-(3) có tác động thật (đã giao/đã xuất hóa đơn): không thể sửa dòng
        #   cũ, phải tách dòng — đưa dòng cũ về SL 0 (giữ lịch sử) và tạo dòng mới cho
        #   sản phẩm mới, đi theo đúng luồng "chờ kho duyệt" hiện có cho dòng mới.
        was_locked = bool(self.locked)
        needs_temp_unlock = (
            was_locked
            and not defer_quantity
            and any(sol.product_id != misa_data['product'] for misa_data, sol in matched_pairs)
        )
        if needs_temp_unlock:
            _logger.info("🔓 Tạm mở khóa SO %s để đồng bộ đổi sản phẩm từ MISA", self.name)
            self.action_unlock()

        try:
            # Cập nhật các SOL đã match
            for misa_data, sol in matched_pairs:
                old_qty = float(sol.product_uom_qty or 0.0)
                new_qty = float(misa_data['qty'] or 0.0)
                product_changed = sol.product_id != misa_data['product']

                if product_changed and not defer_quantity and not sol.product_updatable:
                    qty_delivered_now = float(getattr(sol, 'qty_delivered', 0.0) or 0.0)
                    qty_invoiced_now = float(getattr(sol, 'qty_invoiced', 0.0) or 0.0)
                    has_real_impact = qty_invoiced_now > 0.001 or qty_delivered_now > 0.001
                    pending_moves = sol.move_ids.filtered(lambda m: m.state not in ('done', 'cancel'))

                    if not has_real_impact and pending_moves:
                        _logger.info(
                            "Hủy %s phiếu giao treo (sản phẩm cũ %s) để đổi sang %s trên CRM line %s",
                            len(pending_moves), sol.product_id.display_name,
                            misa_data['product'].display_name, misa_data['crm_line_id'],
                        )
                        pending_moves._action_cancel()
                        # move_ids_without_package không lọc theo state nên phiếu pick
                        # vẫn hiển thị move đã cancel; unlink hẳn vì move này chưa giao
                        # gì (qty_delivered=0) nên không có giá trị lưu vết.
                        pending_moves.unlink()
                        # product_updatable giờ recompute lại thành True, rơi xuống xử lý
                        # write bình thường bên dưới.
                    elif has_real_impact:
                        # Không thể set thẳng về 0 nếu đã giao: sale_stock chặn hạ
                        # product_uom_qty xuống dưới qty_delivered ("cannot be decreased
                        # below the amount already delivered"). Hạ về đúng mức đã giao —
                        # tức không còn gì phải giao thêm cho sản phẩm cũ.
                        old_line_floor_qty = max(qty_delivered_now, 0.0)
                        _audit(
                            misa_data, sol, _('Sản phẩm'),
                            _("%s (giữ lại SL %g, đã tác động kho/hóa đơn)") % (
                                sol.product_id.display_name, old_line_floor_qty,
                            ),
                            _("Tách dòng mới: %s, chờ kho duyệt") % misa_data['product'].display_name,
                        )
                        qty_changes.append({
                            'crm_line_id': misa_data['crm_line_id'],
                            'code': "%s → %s" % (
                                sol.product_id.default_code or sol.product_id.display_name,
                                misa_data['code'],
                            ),
                            'old_qty': old_qty,
                            'new_qty': new_qty,
                        })
                        sol.write({'product_uom_qty': old_line_floor_qty, 'misa_crm_line_id': False})
                        _logger.info(
                            "🔀 Tách CRM line %s: giữ %s ở SL %g (đã tác động), chuyển sang "
                            "sản phẩm mới %s chờ kho duyệt",
                            misa_data['crm_line_id'], sol.product_id.display_name,
                            old_line_floor_qty, misa_data['product'].display_name,
                        )
                        unmatched_misa.append(misa_data)
                        continue

                stock_changed = product_changed or abs(old_qty - new_qty) >= 0.01
                if product_changed:
                    _audit(
                        misa_data, sol, _('Sản phẩm'),
                        sol.product_id.display_name, misa_data['product'].display_name,
                    )
                if abs(old_qty - new_qty) >= 0.01:
                    _audit(misa_data, sol, _('Số lượng'), "%g" % old_qty, "%g" % new_qty)
                if abs(float(sol.price_unit or 0.0) - float(misa_data['price'] or 0.0)) >= 0.01:
                    _audit(
                        misa_data, sol, _('Đơn giá'),
                        "%g" % float(sol.price_unit or 0.0),
                        "%g" % float(misa_data['price'] or 0.0),
                    )
                if abs(float(sol.discount or 0.0) - float(misa_data['discount'] or 0.0)) >= 0.0001:
                    _audit(
                        misa_data, sol, _('Chiết khấu (%)'),
                        "%g" % float(sol.discount or 0.0),
                        "%g" % float(misa_data['discount'] or 0.0),
                    )
                if (
                    misa_data['loyalty_discount_present']
                    and abs(
                        float(sol.loyalty_discount_pct or 0.0)
                        - float(misa_data['loyalty_discount_pct'] or 0.0)
                    ) >= 0.0001
                ):
                    _audit(
                        misa_data, sol, _('CK Loyalty (%)'),
                        "%g" % float(sol.loyalty_discount_pct or 0.0),
                        "%g" % float(misa_data['loyalty_discount_pct'] or 0.0),
                    )
                if (sol.name or '').strip() != (misa_data['name'] or '').strip():
                    _audit(misa_data, sol, _('Mô tả'), sol.name, misa_data['name'])
                if (sol.note or '').strip() != (misa_data['note'] or '').strip():
                    _audit(misa_data, sol, _('Ghi chú dòng'), sol.note, misa_data['note'])
                if stock_changed:
                    qty_changes.append({
                        'crm_line_id': misa_data['crm_line_id'],
                        'code': (
                            "%s → %s" % (sol.product_id.default_code or sol.product_id.display_name, misa_data['code'])
                            if product_changed else misa_data['code']
                        ),
                        'old_qty': old_qty,
                        'new_qty': new_qty,
                    })
                defer_product_change = bool(defer_quantity and product_changed)
                vals_line = {
                    'misa_crm_line_id': misa_data['crm_line_id'] or sol.misa_crm_line_id,
                }
                if not defer_product_change:
                    vals_line.update({
                        'name': misa_data['name'],
                        'price_unit': misa_data['price'],
                        'discount': misa_data['discount'],
                        'note': misa_data['note'],
                        'x_studio_product_status': misa_data['status'],
                    })
                    if misa_data['loyalty_discount_present']:
                        vals_line['loyalty_discount_pct'] = misa_data[
                            'loyalty_discount_pct'
                        ]
                if not (defer_quantity and stock_changed):
                    vals_line['product_id'] = misa_data['product'].id
                    vals_line['product_uom_qty'] = new_qty
                    if product_changed and misa_data['product'].uom_id:
                        vals_line['product_uom'] = misa_data['product'].uom_id.id
                if (not defer_quantity or not stock_changed) and not product_changed and not misa_data['is_default_uom'] and misa_data['product'].uom_id:
                    vals_line['product_uom'] = misa_data['product'].uom_id.id

                if not defer_product_change:
                    if misa_data['tax_ids']:
                        vals_line['tax_id'] = [(6, 0, misa_data['tax_ids'])]
                    else:
                        vals_line['tax_id'] = [(5, 0, 0)]

                sol.write(vals_line)
                _logger.info("✏️ Cập nhật SOL %s: qty=%.2f", misa_data['code'], misa_data['qty'])

            # Tạo mới SOL cho các dòng MISA chưa match (bao gồm cả dòng vừa tách ở trên)
            for misa_data in unmatched_misa:
                new_qty = float(misa_data['qty'] or 0.0)
                new_line_audit = False
                if abs(new_qty) >= 0.01:
                    new_line_audit = _audit(
                        misa_data, None, _('Dòng sản phẩm'), '',
                        _("SL %g; đơn giá %g") % (new_qty, float(misa_data['price'] or 0.0)),
                        change_type='add',
                    )
                    qty_changes.append({
                        'crm_line_id': misa_data['crm_line_id'],
                        'code': misa_data['code'],
                        'old_qty': 0.0,
                        'new_qty': new_qty,
                    })
                if defer_quantity and abs(new_qty) >= 0.01:
                    _logger.info(
                        "Chờ kho duyệt trước khi thêm CRM line %s (%s), qty=%s",
                        misa_data['crm_line_id'], misa_data['code'], new_qty,
                    )
                    continue
                vals_line = {
                    'order_id': self.id,
                    'misa_crm_line_id': misa_data['crm_line_id'] or False,
                    'product_id': misa_data['product'].id,
                    'name': misa_data['name'],
                    'product_uom_qty': misa_data['qty'],
                    'price_unit': misa_data['price'],
                    'discount': misa_data['discount'],
                    'note': misa_data['note'],
                    'x_studio_product_status': misa_data['status'],
                }
                if misa_data['loyalty_discount_present']:
                    vals_line['loyalty_discount_pct'] = misa_data[
                        'loyalty_discount_pct'
                    ]
                if not misa_data['is_default_uom'] and misa_data['product'].uom_id:
                    vals_line['product_uom'] = misa_data['product'].uom_id.id

                if misa_data['tax_ids']:
                    vals_line['tax_id'] = [(6, 0, misa_data['tax_ids'])]
                else:
                    vals_line['tax_id'] = [(5, 0, 0)]

                new_sale_line = SaleLine.create(vals_line)
                if new_line_audit:
                    new_line_audit['sale_order_line_id'] = new_sale_line.id
                _logger.info("➕ Tạo mới SOL %s: qty=%.2f", misa_data['code'], misa_data['qty'])

            # ===== XỬ LÝ SẢN PHẨM BỊ XÓA KHỎI MISA =====
            # KHÔNG xóa SOL, chỉ set qty = 0 để giữ lịch sử và cho Odoo xử lý

            for sol in unmatched_sols:
                code = sol.product_id.default_code or sol.product_id.name

                # Dòng có CRM Line ID luôn là dòng MISA. Với dữ liệu legacy chưa có
                # ID, chỉ xem là dòng bị xóa ở lần đồng bộ đầu tiên của đơn chưa có
                # snapshot, hoặc khi snapshot chờ duyệt đã ghi nhận chính dòng đó.
                if not _is_removed_misa_line(sol):
                    _logger.info(
                        "Giữ nguyên dòng Odoo chưa có CRM Line ID vì đơn đã có lịch sử: %s",
                        code,
                    )
                    continue

                qty_delivered = float(getattr(sol, 'qty_delivered', 0.0) or 0.0)

                # CRM Line ID đã biến mất khỏi response mới = sale đã xóa dòng trên MISA.
                # Giữ record SOL để truy vết nhưng đưa ordered quantity về đúng 0,
                # kể cả khi đã giao/xuất hóa đơn; qty_delivered/qty_invoiced vẫn giữ số thực tế.
                new_qty = 0.0
                old_qty = float(sol.product_uom_qty or 0.0)
                if abs(old_qty - new_qty) >= 0.01:
                    _audit(
                        None, sol, _('Dòng sản phẩm'),
                        _("SL %g; đơn giá %g") % (old_qty, float(sol.price_unit or 0.0)),
                        _("SL %g") % new_qty,
                        change_type='remove',
                    )
                    qty_changes.append({
                        'crm_line_id': sol.misa_crm_line_id,
                        'code': code,
                        'old_qty': old_qty,
                        'new_qty': new_qty,
                    })
                if defer_quantity:
                    _logger.info(
                        "Chờ kho duyệt trước khi đưa CRM line %s (%s) từ %s về %s",
                        sol.misa_crm_line_id or 'legacy', code, old_qty, new_qty,
                    )
                    continue
                sol.write({'product_uom_qty': new_qty})
                _logger.info(
                    "↘️ Set qty=0 cho CRM line %s (%s) không còn trong MISA; qty_delivered=%s được giữ nguyên.",
                    sol.misa_crm_line_id or 'legacy', code, qty_delivered,
                )
        finally:
            if needs_temp_unlock:
                self.action_lock()
                _logger.info("🔒 Khóa lại SO %s sau khi đồng bộ MISA", self.name)

        return {
            'qty_changes': qty_changes,
            'audit_changes': audit_changes,
            'quantity_deferred': bool(defer_quantity and qty_changes),
            'line_snapshot': line_snapshot,
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

    def _misa_warehouse_touched_pickings(self):
        """Phiếu đã được in, mở trên app kho, quét, đóng kiện hoặc hoàn tất."""
        self.ensure_one()
        active_pickings = self.picking_ids.filtered(lambda p: p.state != 'cancel')

        def _was_touched(picking):
            if picking.state in ('done', 'in_progress'):
                return True
            if 'x_printed' in picking._fields and picking.x_printed:
                return True
            if 'x_pick_print_start_at' in picking._fields and picking.x_pick_print_start_at:
                return True
            if 'x_pack_actual_start_at' in picking._fields and picking.x_pack_actual_start_at:
                return True
            if 'hlv_barcode_auto_cleared' in picking._fields and picking.hlv_barcode_auto_cleared:
                return True
            for move_line in picking.move_line_ids:
                if 'qty_scanned' in move_line._fields and (move_line.qty_scanned or 0.0) > 0.0:
                    return True
                if move_line.result_package_id:
                    return True
                if (
                    'package_transfer_qty_set' in move_line._fields
                    and move_line.package_transfer_qty_set
                ):
                    return True
            return False

        return active_pickings.filtered(_was_touched)

    def _misa_qty_change_summary(self, changes):
        rows = []
        for change in changes or []:
            rows.append(
                "%s: %g → %g (CRM line %s)" % (
                    change.get('code') or _('Không mã'),
                    change.get('old_qty') or 0.0,
                    change.get('new_qty') or 0.0,
                    change.get('crm_line_id') or '-',
                )
            )
        return "\n".join(rows)

    def _misa_record_sync_snapshot_history(self, sync_result, header_data, pending):
        """Lưu một phiên bản thay đổi có thể truy vết; phiên bản mới thay phiên bản pending cũ."""
        self.ensure_one()
        snapshot_payload = sync_result.get('line_snapshot') or []
        audit_changes = sync_result.get('audit_changes') or []
        current = self.misa_qty_sync_pending_history_id.sudo()

        # Cùng một snapshot được resync lại thì không tạo thêm lịch sử trùng.
        if pending and current and current.snapshot_payload == snapshot_payload:
            return current

        now = fields.Datetime.now()
        history = self.env['misa.sale.sync.snapshot']
        if audit_changes:
            summary = "\n".join(
                "[%s] %s: %s → %s" % (
                    change.get('product_code') or '-',
                    change.get('field_name') or _('Thay đổi'),
                    change.get('old_value') or '-',
                    change.get('new_value') or '-',
                )
                for change in audit_changes
            )
            crm_modified_at = False
            crm_modified_at_raw = (
                header_data.get('ModifiedDate')
                or header_data.get('LastModifiedDate')
                or header_data.get('UpdatedDate')
            )
            if crm_modified_at_raw:
                try:
                    # ModifiedDate của CRM là giờ Việt Nam dạng wall-clock, kể cả khi payload
                    # có gắn timezone marker. Chuyển đúng về UTC trước khi lưu fields.Datetime.
                    crm_wall_time = dtparse(str(crm_modified_at_raw)).replace(tzinfo=None)
                    crm_modified_at = MISA_CRM_TZ.localize(
                        crm_wall_time
                    ).astimezone(pytz.UTC).replace(tzinfo=None)
                except Exception:
                    crm_modified_at = False
            history = self.env['misa.sale.sync.snapshot'].sudo().create({
                'sale_order_id': self.id,
                'misa_order_id': str(self.misa_id or ''),
                'fetched_at': now,
                'fetched_by_id': self.env.user.id,
                'crm_owner': header_data.get('OwnerIDText') or False,
                'crm_modified_by': (
                    header_data.get('ModifiedByIDText')
                    or header_data.get('ModifiedByName')
                    or header_data.get('ModifiedByText')
                    or header_data.get('LastModifiedByIDText')
                    or False
                ),
                'crm_modified_at': crm_modified_at,
                'crm_modified_at_raw': str(crm_modified_at_raw) if crm_modified_at_raw else False,
                'state': 'pending' if pending else 'applied',
                'summary': summary,
                'warehouse_summary': self._misa_qty_change_summary(
                    sync_result.get('qty_changes') or []
                ),
                'snapshot_payload': snapshot_payload,
                'change_count': len(audit_changes),
                'line_ids': [(0, 0, change) for change in audit_changes],
            })

        if current:
            vals = {'state': 'superseded'}
            if history:
                vals['replaced_by_id'] = history.id
            current.write(vals)
        return history

    def _misa_notify_warehouse(self, title, detail=None, send_zalo=False):
        """Ghi chatter; chỉ gửi Zalo khi caller xác nhận đúng điều kiện nghiệp vụ."""
        self.ensure_one()
        body = Markup("<b>{}</b>").format(title)
        if detail:
            body += Markup("<br/><pre>{}</pre>").format(detail)

        open_pickings = self.picking_ids.filtered(lambda p: p.state != 'cancel')
        partner_ids = set()
        for picking in open_pickings:
            if 'x_pack_packer_user_id' in picking._fields and picking.x_pack_packer_user_id:
                partner_ids.add(picking.x_pack_packer_user_id.partner_id.id)
        for picking in open_pickings:
            picking.message_post(body=body, partner_ids=list(partner_ids))
        self.message_post(body=body, partner_ids=list(partner_ids))

        if send_zalo:
            try:
                zalo_config = self.env['hlv.zalo.stock.notification'].sudo()._get_active_config()
                if not zalo_config:
                    _logger.warning("MISA warehouse Zalo notification skipped for %s: no active config", self.name)
                    return
                result = zalo_config.send_so_warehouse_notification(
                    self.sudo(),
                    str(title),
                    str(detail) if detail else None,
                )
                _logger.info("MISA warehouse Zalo notification result for %s: %s", self.name, result)
            except Exception as exc:
                _logger.exception("MISA warehouse Zalo notification failed for %s: %s", self.name, exc)

    def _misa_sync_open_picking_contact(self):
        """Giữ phiếu kho mở theo đúng liên hệ giao hàng của SO sau resync/approve."""
        self.ensure_one()
        shipping_partner = self.partner_shipping_id or self.partner_id
        if shipping_partner:
            self.picking_ids.filtered(
                lambda picking: picking.state not in ('done', 'cancel')
            ).write({'partner_id': shipping_partner.id})

    def _sync_misa_header_in_place(self, data, headers):
        """Cập nhật header trên chính SO hiện tại, không thay record và không đụng move."""
        self.ensure_one()
        env = self.env
        misa_order_id = data.get('ID') or data.get('CustomID') or self.misa_id
        raw_owner = str(data.get('OwnerIDText') or '').strip()
        owner_code = raw_owner
        if raw_owner.endswith(')') and '(' in raw_owner:
            owner_code = raw_owner.rsplit('(', 1)[-1][:-1].strip()
        sale_order_date = data.get('SaleOrderDate')
        if sale_order_date:
            try:
                sale_order_date = dtparse(str(sale_order_date)).date()
            except Exception:
                sale_order_date = None
        owner_date = {
            'owner_code': owner_code or None,
            'sale_order_date': sale_order_date,
            'misa_delivery': (data.get('CustomField14') or '').strip() or None,
            'shipping_contact': (data.get('ShippingContactIDText') or '').strip() or None,
            'httt': (data.get('CustomField15') or '').strip() or None,
            'htgh': (data.get('CustomField16') or '').strip() or None,
            'misa_note': (data.get('CustomField21') or '').strip() or None,
        }
        # Both helpers read the same SaleOrder FormDataNew payload. Only make a
        # second request for legacy responses that omit all supplemental fields.
        if not any(owner_date.values()):
            try:
                owner_date = env['misa.api.utils'].get_saleorder_owner_and_date(
                    misa_order_id, headers,
                ) or {}
            except Exception as exc:
                _logger.warning("Không lấy được header bổ sung MISA cho SO=%s: %s", misa_order_id, exc)

        partner_name = data.get('AccountIDText') or data.get('BillingAccountIDText') or _('Khách hàng MISA')
        account_id = data.get('AccountID') or data.get('AccountId')
        partner = None
        misa_code = None
        tax_code = None
        if account_id:
            try:
                partner = env['misa.api.utils']._sync_customer_from_misa_account_api(account_id, headers)
                if partner:
                    # The account API above already supplies AccountNumber and
                    # TaxCode and persists them on the partner. Avoid fetching
                    # Account/FormDataNew again for the same information.
                    misa_code = partner.ref or partner.company_registry
                    tax_code = partner.vat
                else:
                    identity = env['misa.api.utils'].get_account_identity(account_id, headers) or {}
                    misa_code = identity.get('account_number') or identity.get('id')
                    tax_code = identity.get('taxcode')
            except Exception as exc:
                _logger.warning("Không đồng bộ được khách MISA AccountID=%s: %s", account_id, exc)
        if not partner:
            partner = env['odoo.utils']._get_or_create_partner(
                partner_name, misa_code=misa_code, tax_code=tax_code,
            )
        partner = partner.commercial_partner_id or partner

        shipping_address = (data.get('ShippingAddress') or '').strip()
        shipping_addr = shipping_address or data.get('BillingAddress') or ''
        shipping_contact = owner_date.get('shipping_contact') or data.get('ShippingContactIDText')
        shipping_id = False
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
        try:
            delivery_contact = env['sale.api.import.wizard']._get_or_create_delivery_contact(
                parent_partner=partner,
                addr_str=shipping_addr,
                phone=data.get('Phone'),
                province_text=data.get('ShippingProvinceIDText') or data.get('BillingProvinceIDText'),
                contact_name=shipping_contact.strip() if shipping_contact else None,
                is_e_account=(partner_name in e_accounts),
            )
            shipping_id = delivery_contact.id
        except Exception as exc:
            _logger.warning("Không cập nhật được địa chỉ giao hàng SO %s: %s", self.name, exc)

        crm_order_no = str(data.get('SaleOrderNo') or '').strip()
        crm_order_name = str(data.get('SaleOrderName') or '').strip()
        vals = {
            'name': crm_order_no or crm_order_name or self.name,
            'partner_id': partner.id,
            'partner_invoice_id': partner.id,
            'partner_shipping_id': shipping_id or self.partner_shipping_id.id or partner.id,
            'origin': crm_order_name or self.origin,
            'misa_id': str(misa_order_id) if misa_order_id else self.misa_id,
            'misa_shipping_address': shipping_address or False,
            'x_studio_zns': bool(data.get('CustomField23', False)),
            'x_studio_sdt_giao_hang': data.get('Phone') or False,
        }
        for source_key, field_name in (
            ('owner_code', 'x_studio_misa_saler_code'),
            ('sale_order_date', 'x_studio_misa_order_date'),
            ('misa_delivery', 'x_studio_misa_delivery'),
            ('httt', 'x_studio_httt'),
            ('htgh', 'x_studio_htgh'),
            ('misa_note', 'x_studio_misa_note'),
        ):
            if owner_date.get(source_key) and field_name in self._fields:
                vals[field_name] = owner_date[source_key]

        book_date = data.get('BookDate') or data.get('InvoiceDate') or data.get('DeliveryDate')
        deadline_date = data.get('DeadlineDate')
        if book_date:
            try:
                vals['date_order'] = dtparse(book_date).replace(tzinfo=None)
            except Exception:
                pass
        if deadline_date:
            try:
                vals['commitment_date'] = dtparse(deadline_date).replace(tzinfo=None)
            except Exception:
                pass

        vals = {key: value for key, value in vals.items() if key in self._fields}
        self.write(vals)
        self._misa_sync_open_picking_contact()

    def action_resync_from_misa(self, prefetched_lines=None, misa_headers=None):
        """Đồng bộ tại chỗ theo CRM line ID và để Odoo tự quản lý stock moves."""
        self.ensure_one()
        if not self.misa_id:
            raise UserError(_("Thiếu MISA ID trên đơn bán."))

        headers = misa_headers
        if headers is None:
            headers, _crm_token = self._misa_headers()
        data = self._misa_fetch_order(headers=headers)
        misa_order_id = data.get('ID') or data.get('CustomID') or self.misa_id
        status_id = data.get('RevenueStatusID')
        status_text = (data.get('RevenueStatusIDText') or '').strip().lower()

        # Hủy đơn là quyết định từ CRM: không cần kho duyệt, dùng action_cancel chuẩn Odoo.
        if str(status_id or '').strip() == '4' or status_text == 'từ chối ghi':
            self._misa_notify_warehouse(
                _("Đơn %s đã bị hủy ghi doanh số, Lưu ý : sale đang tiến hành sửa đơn.") % self.name,
            )
            if self.state != 'cancel':
                self.action_cancel()
            if self.misa_qty_sync_pending_history_id:
                self.misa_qty_sync_pending_history_id.sudo().write({'state': 'superseded'})
            self.write({
                'misa_qty_sync_pending': False,
                'misa_qty_sync_pending_at': False,
                'misa_qty_sync_pending_summary': False,
                'misa_qty_sync_pending_snapshot': False,
                'misa_qty_sync_pending_history_id': False,
            })
            self._misa_clear_sale_edit_lock()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Đã hủy đơn theo MISA"),
                    'message': self.name,
                    'type': 'warning',
                },
            }

        # Nếu SO hiện tại đang ở trạng thái cancel (do hủy thủ công trên Odoo)
        # nhưng MISA CRM không hủy => Reset về draft để cho phép cập nhật lại
        if self.state == 'cancel':
            self.action_draft()

        lines = (
            prefetched_lines
            if prefetched_lines is not None
            else self._misa_fetch_lines(misa_order_id, headers=headers)
        )
        if self.env.context.get('misa_assign_warehouse_from_lines'):
            warehouse = self.env['stock.warehouse'].browse(
                self.env.context.get('misa_resolved_warehouse_id') or []
            ).exists()
            if not warehouse:
                warehouse = self._misa_warehouse_from_sale_lines(lines)

        warehouse_changed = bool(
            self.env.context.get('misa_assign_warehouse_from_lines')
            and warehouse
            and self.warehouse_id != warehouse
        )
        touched_pickings = self._misa_warehouse_touched_pickings()
        pickings_to_rebuild = self.env['stock.picking']
        previous_warehouse = self.warehouse_id

        if warehouse_changed:
            if touched_pickings:
                raise UserError(_(
                    "Không thể tự động đổi kho từ %(old_warehouse)s sang "
                    "%(new_warehouse)s vì các phiếu kho sau đã được tác động: %(pickings)s."
                ) % {
                    'old_warehouse': previous_warehouse.name or '-',
                    'new_warehouse': warehouse.name,
                    'pickings': ', '.join(touched_pickings.mapped('name')),
                })

            pickings_to_rebuild = self.picking_ids.filtered(
                lambda picking: picking.state not in ('done', 'cancel')
            )
            if pickings_to_rebuild:
                old_picking_names = ', '.join(pickings_to_rebuild.mapped('name'))
                pickings_to_rebuild.sudo().action_cancel()
                _logger.info(
                    "🏭 Hủy chuỗi phiếu kho cũ chưa tác động của SO %s trước khi đổi kho: %s",
                    self.name,
                    old_picking_names,
                )

        self._sync_misa_header_in_place(data, headers)
        if self.env.context.get('misa_assign_warehouse_from_lines'):
            # Header sync can recompute warehouse_id from the current user's
            # default warehouse. Re-assert the warehouse resolved from MISA
            # even when the bootstrap SO already had that warehouse before
            # syncing the partner/header.
            if warehouse and self.warehouse_id != warehouse:
                warehouse_after_header = self.warehouse_id
                self.write({'warehouse_id': warehouse.id})
                _logger.info(
                    "🏭 Khôi phục kho MISA cho SO %s sau sync header: %s → %s",
                    self.name,
                    warehouse_after_header.name or "-",
                    warehouse.name,
                )
            if warehouse:
                _logger.info(
                    "Kho SO %s sau khi dong bo header: %s",
                    self.name, self.warehouse_id.name,
                )

        sync_result = self._sync_so_lines_from_misa_no_picking(
            lines,
            headers,
            defer_quantity=bool(touched_pickings),
        )

        if warehouse_changed and pickings_to_rebuild:
            old_picking_ids = set(pickings_to_rebuild.ids)
            stock_lines = self.order_line.filtered(
                lambda line: not line.display_type and line.product_uom_qty > 0
            )
            stock_lines.sudo()._action_launch_stock_rule()
            self.invalidate_recordset(['picking_ids'])
            self._misa_sync_open_picking_contact()
            new_pickings = self.picking_ids.filtered(
                lambda picking: picking.id not in old_picking_ids
                and picking.state != 'cancel'
            )
            _logger.info(
                "🏭 Tạo lại chuỗi phiếu kho SO %s theo kho %s: %s",
                self.name,
                warehouse.name,
                ', '.join(new_pickings.mapped('name')) or '-',
            )

        qty_changes = sync_result.get('qty_changes') or []
        history = self._misa_record_sync_snapshot_history(
            sync_result,
            data,
            pending=bool(sync_result.get('quantity_deferred')),
        )
        if sync_result.get('quantity_deferred'):
            summary = self._misa_qty_change_summary(qty_changes)
            was_pending = self.misa_qty_sync_pending
            old_summary = self.misa_qty_sync_pending_summary or ''
            self.write({
                'misa_qty_sync_pending': True,
                'misa_qty_sync_pending_at': fields.Datetime.now(),
                'misa_qty_sync_pending_summary': summary,
                'misa_qty_sync_pending_snapshot': sync_result.get('line_snapshot') or [],
                'misa_qty_sync_pending_history_id': history.id,
            })
            if not was_pending or old_summary != summary:
                self._misa_notify_warehouse(
                    _("Đơn %s thay đổi số lượng trên MISA và đang chờ kho duyệt.") % self.name,
                    summary,
                    send_zalo=True,
                )
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("Chờ kho duyệt số lượng"),
                    'message': summary,
                    'type': 'warning',
                    'sticky': True,
                },
            }

        self.write({
            'misa_qty_sync_pending': False,
            'misa_qty_sync_pending_at': False,
            'misa_qty_sync_pending_summary': False,
            'misa_qty_sync_pending_snapshot': False,
            'misa_qty_sync_pending_history_id': False,
        })
        self._misa_clear_sale_edit_lock()
        if self.state in ('draft', 'sent'):
            self.action_confirm()
        self._auto_apply_misa_tags()
        if warehouse_changed and pickings_to_rebuild:
            self.message_post(body=_(
                "Đã đồng bộ MISA và tạo lại chuỗi phiếu kho theo kho %(warehouse)s."
            ) % {'warehouse': warehouse.name})
        else:
            self.message_post(body=_(
                "Đã đồng bộ MISA tại chỗ; giữ nguyên SO và các phiếu kho hiện có."
            ))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }

    def action_resync_from_misa_hard(self):
        """Alias tương thích view cũ; tuyệt đối không khôi phục luồng hard/delete move."""
        return self.action_resync_from_misa()

    def action_approve_misa_quantity_sync(self):
        self.ensure_one()
        if not self.misa_qty_sync_pending:
            raise UserError(_("Đơn không có thay đổi số lượng MISA đang chờ duyệt."))
        if not self.env.user.has_group('stock.group_stock_user'):
            raise UserError(_("Chỉ người dùng kho mới được duyệt thay đổi số lượng MISA."))
        snapshot = self.misa_qty_sync_pending_snapshot
        if not isinstance(snapshot, list):
            raise UserError(_(
                "Đơn chờ duyệt này chưa có snapshot. Vui lòng đồng bộ MISA lại một lần để tạo snapshot mới."
            ))
        approver_name = self.env.user.name
        order = self.sudo()
        pending_summary = order.misa_qty_sync_pending_summary
        pending_history = order.misa_qty_sync_pending_history_id
        legacy_removal_line_ids = (
            pending_history.line_ids.filtered(
                lambda line: (
                    line.change_type == 'remove'
                    and not line.crm_line_id
                    and line.sale_order_line_id
                )
            ).mapped('sale_order_line_id').ids
            if pending_history
            else []
        )
        order.with_context(
            misa_approved_legacy_removal_line_ids=legacy_removal_line_ids,
        )._sync_so_lines_from_misa_no_picking(
            lines=[],
            headers={},
            defer_quantity=False,
            prepared_lines=snapshot,
        )
        order._misa_sync_open_picking_contact()
        if pending_history:
            lines_by_crm_id = {
                line.misa_crm_line_id: line
                for line in order.order_line
                if line.misa_crm_line_id
            }
            for history_line in pending_history.line_ids.filtered(
                lambda line: not line.sale_order_line_id and line.crm_line_id
            ):
                sale_line = lines_by_crm_id.get(history_line.crm_line_id)
                if sale_line:
                    history_line.sudo().write({'sale_order_line_id': sale_line.id})
        order.write({
            'misa_qty_sync_pending': False,
            'misa_qty_sync_pending_at': False,
            'misa_qty_sync_pending_summary': False,
            'misa_qty_sync_pending_snapshot': False,
            'misa_qty_sync_pending_history_id': False,
        })
        order._misa_clear_sale_edit_lock()
        if pending_history:
            pending_history.sudo().write({
                'state': 'applied',
                'approved_at': fields.Datetime.now(),
                'approved_by_id': self.env.user.id,
            })
        if order.state in ('draft', 'sent'):
            order.action_confirm()
        order._auto_apply_misa_tags()
        order._misa_notify_warehouse(
            _("Kho (%s) đã duyệt thay đổi số lượng MISA cho đơn %s.") % (approver_name, order.name),
            pending_summary,
        )
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': order.id,
            'target': 'current',
        }
# =====================API
    @api.model
    def api_resync_by_misa(self, misa_order_id, warehouse_id=None, create_when_missing=True):
        """
        Public API (RPC/JSON-RPC) để resync đơn bán theo MISA Order ID.
        - Nếu tìm thấy SO có misa_id => cập nhật tại chỗ theo CRM line ID.
        - Nếu không thấy và create_when_missing=True => tạo SO rồi nạp dữ liệu MISA tại chỗ.
        Trả về: dict {'ok': bool, 'res_id': int or None, 'name': str or None, 'detail': str or None}
        """
        misa_order_id = (str(misa_order_id or '')).strip()
        if not misa_order_id:
            raise UserError(_("Thiếu misa_order_id"))
        # 1) Tìm SO hiện hữu theo misa_id
        so = self.search([('misa_id', '=', misa_order_id)], limit=1)
        if so:
            misa_headers, _crm_token = self._misa_headers()
            prefetched_lines = self._misa_fetch_lines(
                misa_order_id,
                headers=misa_headers,
            )
            if warehouse_id:
                misa_warehouse = self.env['stock.warehouse'].browse(
                    int(warehouse_id)
                ).exists()
                if not misa_warehouse:
                    raise UserError(_("Không tìm thấy kho Odoo ID %s") % warehouse_id)
            else:
                misa_warehouse = self._misa_warehouse_from_sale_lines(
                    prefetched_lines
                )

            so.sudo().with_context(
                misa_assign_warehouse_from_lines=True,
                misa_resolved_warehouse_id=misa_warehouse.id or False,
            ).action_resync_from_misa(
                prefetched_lines=prefetched_lines,
                misa_headers=misa_headers,
            )
            return {
                'ok': True,
                'res_id': so.id,
                'name': so.name,
                'warehouse_id': so.warehouse_id.id,
                'warehouse_name': so.warehouse_id.name,
                'detail': (
                    'cancelled_from_misa' if so.state == 'cancel'
                    else 'waiting_warehouse_approval' if so.misa_qty_sync_pending
                    else 'resynced_existing_in_place'
                ),
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
        prefetched_lines = None
        misa_headers = None
        misa_warehouse = self.env['stock.warehouse']
        if warehouse_id:
            vals['warehouse_id'] = int(warehouse_id)
        else:
            # sale.order.warehouse_id is precomputed during create(). Resolve the
            # MISA warehouse first so the bootstrap order never starts at the
            # current user's default warehouse (usually TSN).
            misa_headers, _crm_token = self._misa_headers()
            prefetched_lines = self._misa_fetch_lines(
                misa_order_id,
                headers=misa_headers,
            )
            misa_warehouse = self._misa_warehouse_from_sale_lines(prefetched_lines)
            if misa_warehouse:
                vals['warehouse_id'] = misa_warehouse.id
            
        so_boot = self.create(vals)
        _logger.info(
            "Tao SO bootstrap MISA %s voi kho: %s",
            misa_order_id, so_boot.warehouse_id.name,
        )
        so_boot.sudo().with_context(
            misa_assign_warehouse_from_lines=not bool(warehouse_id),
            misa_resolved_warehouse_id=misa_warehouse.id or False,
        ).action_resync_from_misa(
            prefetched_lines=prefetched_lines,
            misa_headers=misa_headers,
        )
        _logger.info(
            "Hoan tat dong bo SO %s, kho cuoi cung: %s",
            so_boot.name, so_boot.warehouse_id.name,
        )
        return {
            'ok': True,
            'res_id': so_boot.id,
            'name': so_boot.name,
            'detail': 'created_cancelled_from_misa' if so_boot.state == 'cancel' else 'created_and_synced_in_place',
        }


