from odoo import models, fields, _
import logging
import json
from datetime import datetime, timedelta, timezone  # ⬅️ NEW
import uuid
import requests


_logger = logging.getLogger(__name__)

class MisaPOFetch(models.TransientModel):
    _name = "misa.po.fetch"
    _description = "MISA PO Fetch"
    date_from = fields.Date(string="Từ ngày", required=True)
    date_to = fields.Date(string="Đến ngày", required=True)
    # ================== HELPERS QUY ĐỔI UOM ==================

    def _misa_get_product_id_by_code(self, product_code, product_name, crm_headers):
        """
        Gọi API DataPaging để lấy ProductID từ ProductCode.
        Trả về ProductID (string) hoặc None nếu không tìm thấy.
        """
        if not product_code:
            return None
        
        url = "https://amisapp.misa.vn/crm/g2/api/business/Product/Grid"
        
        payload = {
            "Columns": "SUQsUHJvZHVjdENvZGUsUHJvZHVjdE5hbWUsUHJvZHVjdENhdGVnb3J5SUQsUHJvZHVjdENhdGVnb3J5SURUZXh0LFVzYWdlVW5pdElELFVzYWdlVW5pdElEVGV4dCxVbml0UHJpY2UsVGF4SUQsVGF4SURUZXh0LElzU2V0UHJvZHVjdCxGb3JtTGF5b3V0SUQsRm9ybUxheW91dElEVGV4dCxPd25lcklELE93bmVySURUZXh0LElzU3lzdGVtLEF2YXRhcg==",  # Base64: ID,ProductCode,ProductName
            "Sorts": [],
            "Start": 0,
            "Page": 1,
            "PageSize": 100,
            "Filters": [
                {
                    "Group": None,
                    "Addition": 1,
                    "InputType": 1,
                    "IsFromFormula": True,
                    "Operator": 1,
                    "Property": "ProductCode",
                    "Text": product_code,
                    "Value": product_code
                },
                {
                    "Group": None,
                    "Addition": 1,
                    "InputType": 1,
                    "IsFromFormula": True,
                    "Operator": 1,
                    "Property": "ProductName",
                    "Text": product_name,
                    "Value": product_name
                }
            ],
            "Formula": "( 1 OR 2 )",
            "LayoutCode": "Product",
            "DefaultTotal": False,
            "IsMappingData": False,
            "MappingValueObject": {},
            "IsApproved": False,
            "CustomPagingData": {},
            "IsUsedELTS": True,
            "ListGmailPage": [],
            "ListFacebookPage": {},
            "IsListPaging": True,
            "IsGetCache": True,
            "IsCheckInactive": False,
            "IsConverted": False,
            "SessionID": str(uuid.uuid4()),
            "LayoutCodeCheckPermission": "Product",
            "AISearchKeyword": ""
        }
        
        try:
            resp = requests.post(url, headers=crm_headers, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            _logger.warning("✅ Lấy được dữ liệu cho ProductCode '%s': %s", product_code, data)
            
            products = data.get("Data", [])
            if products and len(products) > 0:
                product_id = products[0].get("ID")
                if product_id:
                    return str(product_id)
                
                    
        except Exception as e:
            _logger.exception("Lỗi khi lấy ProductID từ ProductCode '%s': %s", product_code, e)
        
        return None


    def _misa_fetch_conversion_units(self, product_code, crm_headers):
        """
        Gọi Product/DataSubPaging để lấy quy đổi UoM theo đúng payload bạn yêu cầu.
        """
        if not product_code:
            return []

        product_id = self._misa_get_product_id_by_code(product_code, None, crm_headers)
        if not product_id:
            _logger.warning(
                "MISA UoM conversions: product_code=%r has no matching ProductID",
                product_code,
            )
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
            resp = requests.post(url, headers=crm_headers, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            conversions = data.get("Data", []) or []
         
            return conversions
        except Exception as e:
            _logger.exception("❗ Lỗi gọi Product/DataSubPaging: %s", e)
            return []

    def _convert_qty_price_to_default_uom(self, product, misa_uom_text, qty, price, misa_product_code, crm_headers):
        """
        Chuyển qty/price từ đơn vị lấy từ MISA (misa_uom_text) về đơn vị mặc định của product (product.uom_id).
        Trả về: (qty_base, price_base, uom_is_default)
        - uom_is_default = True nếu misa_uom_text trùng default (không cần convert)
        """
        default_uom_name = (product.uom_id and product.uom_id.name) or ""
        if not misa_uom_text or misa_uom_text.strip().lower() == default_uom_name.strip().lower():
            return qty, price, True  # không cần đổi

        # Lấy bảng quy đổi theo ProductID
        conversions = self._misa_fetch_conversion_units(misa_product_code, crm_headers) if misa_product_code else []
        _logger.warning(
            "MISA UoM conversion lookup: product_code=%r requested_uom=%r "
            "default_uom=%r candidates=%r",
            misa_product_code,
            misa_uom_text,
            default_uom_name,
            [
                c.get("ConversionUnitIDText")
                for c in (conversions or [])
            ],
        )
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
    

    def _get_or_create_vn_vat(self, rate, use='purchase'):
        Tax = self.env['account.tax'].with_company(self.env.company)
        TaxGroup = self.env['account.tax.group'].with_company(self.env.company)

        rate = float(rate)

        # 1) Lấy/ tạo Tax Group "VAT"
        country_vn = self.env['res.country'].search([('code', '=', 'VN')], limit=1)
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

        # 3) Tạo thuế mới và GÁN tax_group_id
        rate_str = str(int(rate)) if float(rate).is_integer() else str(rate)
        return Tax.create({
            'name': f'VAT VN {rate_str}%',
            'type_tax_use': use,          # 'purchase' cho mua hàng
            'amount_type': 'percent',
            'amount': rate,
            'company_id': self.env.company.id,
            'price_include': False,
            'country_id': country_vn.id or False,
            'tax_group_id': vat_group.id,  # <-- BẮT BUỘC
            'active': True,
        })

    def _tax_ids_from_misa_line(self, line):
        """
        Trả về list tax_id cho dòng PO.
        - KCT (không chịu thuế): []  (để trống VAT)
        - 0%: [tax_0_id]
        - x%: [tax_x_id]
        """
        # MISA có thể trả các dạng đánh dấu KCT khác nhau – gom về 1 chỗ để dễ mở rộng
        kct_markers = {'KCT', 'KHONGCHIU', 'NO_VAT', -1, -2}
        raw_rate = line.get('vat_rate', None)
        # Một số API gửi thêm cờ bool (nếu có cột), ta tôn trọng luôn:
        is_not_vat = str(line.get('is_not_vat', '')).lower() in ('1', 'true', 'yes')
        # 1) Nếu có cờ KCT hoặc raw_rate thuộc các marker → không chịu thuế
        if is_not_vat or raw_rate in kct_markers:
            return []
        # 2) Nếu không có vat_rate → coi như KCT
        if raw_rate in (None, '', 'null'):
            return []
        # 3) Còn lại cố gắng parse số %
        try:
            rate = float(raw_rate)
        except Exception:
            # parse không được → coi như KCT
            return []
        # 4) 0% khác KCT → tạo/gắn VAT 0%
        if abs(rate) < 1e-9:
            tax = self._get_or_create_vn_vat(0.0, use='purchase')
            return [tax.id] if tax else []
        # 5) Các mức khác
        tax = self._get_or_create_vn_vat(rate, use='purchase')
        return [tax.id] if tax else []

    def action_fetch_po(self):
        def _to_naive_utc(dt_str: str):
            """'2025-08-26T00:00:00.000+07:00' -> 2025-08-25 17:00:00 (naive UTC)"""
            if not dt_str:
                return False
            aware = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            return aware.astimezone(timezone.utc).replace(tzinfo=None)
        

        
        misa_utils = self.env['misa.api.utils']
        odoo_utils = self.env['odoo.utils']
        misa_config = self.env['misa.config']
        access_token = misa_utils._get_misa_token()

        date_from_utc = datetime.combine(self.date_from, datetime.min.time()) - timedelta(hours=7)
        date_to_utc = datetime.combine(self.date_to, datetime.max.time()) - timedelta(hours=7)

        headers = misa_config.get_default_headers(access_token)
        crm_token = misa_utils._fetch_login_crm_token()
        crm_headers = misa_config.get_crm_header(crm_token)

        payload = {
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
            "loadMode": 2,
            "pageIndex": 1,
            "pageSize": 20, 
            "sort": "[{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":4008,\"desc\":true,\"data_type\":1,\"operand\":1}]",
            "summaryColumns": [5039, 5104, 247],
            "useSp": False,
            "view": 2
        }
        stock_mapping = {
                "HCM": "TSN/Stock",
                "BENCAM": "KBC/Tồn kho",
                "HIENDUC": "KHD/Tồn kho",
                "HCM_SHOWROOM":"TSNSR/Stock",
                "HLV":"HLV/Stock",
                "BẾN CAM": "KBC/Tồn kho",
                "BẾNCAM": "KBC/Tồn kho",
                "HIỀN ĐỨC": "KHD/Tồn kho",
                "ĐÀ NẴNG": "KDN/Tồn kho",
                "ĐÀNẴNG": "KDN/Tồn kho",
                "HIỀNĐỨC": "KHD/Tồn kho",
                "HIENDUC": "KHD/Tồn kho",
                "DANANG": "KDN/Tồn kho",
            }


        page_index = 1
        while True:
            payload["pageIndex"] = page_index
            _logger.info("📄 Đang fetch trang %s...", page_index)
            
            response = misa_utils._fetch_with_retry(
                "https://actapp.misa.vn/g1/api/pu/v1/pu_list/paging_filter_v2",
                headers, payload
            )

            if response.status_code != 200:
                _logger.warning("❌ Gọi API thất bại ở trang %s", page_index)
                break

            page_data = response.json().get("Data", {}).get("PageData", [])
            if not page_data:
                _logger.info("✅ Hết dữ liệu, dừng ở trang %s", page_index)
                break

# ===============================
            for po in page_data:
                refid = po.get("refid")
                supplier_name = po.get("account_object_name")
                refno = po.get("refno", "PO-MISA")
                memo = po.get("journal_memo", "")
                refdate_str = po.get("refdate")  # ngày chứng từ
                custom_field2 = po.get("custom_field2", "")  # điều khoản giao hàng
                misa_purchase_status = po.get("custom_field10", "")  # trạng thái đơn mua hàng từ MISA

                # chỉ lấy đơn "chưa thực hiện" ---
                def _as_bool(val):
                    if isinstance(val, bool):
                        return val
                    return str(val).strip().lower() in ("1", "true", "yes", "y")

                is_srv = _as_bool(po.get("is_created_pu_service", False))
                is_mul = _as_bool(po.get("is_created_pu_multiple", False))

                # nếu CẢ 2 đều false => coi là đã hoàn thành => BỎ QUA
                if (not is_srv) and (not is_mul):
                    _logger.info("⏭️  Bỏ qua PO %s (refid=%s) vì đã hoàn thành (is_created_pu_service=%s, is_created_pu_multiple=%s)", refno, refid, is_srv, is_mul)
                    continue
                
                receive_date_str = po.get("receive_date") or po.get("refdate")
                planned_naive_utc = _to_naive_utc(receive_date_str)


                partner = odoo_utils._get_or_create_partner(supplier_name)

                detail_page_index = 1
                all_detail_lines = []

                while True:
                    detail_payload = {
                        "columns": [2157, 1355, 2161, 4670, 1127,5683, 5274, 3870, 3895, 5279, 308, 5364, 5350, 3404, 2358],
                        "filter": [
                            {
                                "property": 3993,
                                "operator": 7,
                                "operand": 1,
                                "value": refid,
                                "data_type": 10
                            }
                        ],
                        "loadMode": 2,
                        "pageIndex": detail_page_index,
                        "pageSize": 20,
                        "sort": "[{\"property\":4555,\"desc\":false,\"data_type\":4,\"operand\":1}]",
                        "summaryColumns": [3488, 3870, 3895, 3896, 308, 5350],
                        "useSp": False,
                        "view": 92
                    }

                    detail_res = misa_utils._fetch_with_retry(
                        "https://actapp.misa.vn/g1/api/pu/v1/pu_voucher/get_paging_detail",
                        headers, detail_payload
                    )

                    if detail_res.status_code != 200:
                        _logger.warning("Không lấy được chi tiết PO %s ở trang %s", refid, detail_page_index)
                        break

                    page_lines = detail_res.json().get("Data", {}).get("PageData", [])
                    if not page_lines:
                        break

                    all_detail_lines.extend(page_lines)
                    detail_page_index += 1

                # Sau khi loop hết các trang thì gán lại cho lines để xử lý như cũ
                lines = all_detail_lines
                stock_code = (
                    # lines[0].get("stock_code", "").strip().replace(" ", "").upper()
                    lines[0].get("custom_field5", "").strip().replace(" ", "").upper()
                    if lines else None
                                )
                if stock_code not in stock_mapping:
                    _logger.warning("📛 Kho %s không nằm trong mapping, bỏ PO %s", stock_code, refno)
                    continue

                location_name = stock_mapping[stock_code]
                location = self.env['stock.location'].search([
                    ('complete_name', '=', location_name)
                ], limit=1)

                if not location:
                    _logger.warning("❌ Không tìm thấy stock.location cho kho %s (%s)", stock_code, location_name)
                    continue
                
                
                existing_po = self.env["purchase.order"].search([("name", "=", refno)], limit=1)
                if existing_po:
                    _logger.info("⚠️ Bỏ qua đơn hàng %s vì name %s đã tồn tại", refid, refno)
                    continue
                
                warehouse = self.env['stock.warehouse'].search([
                    ('view_location_id', '=', location.location_id.id)
                ], limit=1)

                if not warehouse:
                    _logger.warning("❌ Không tìm thấy warehouse cho kho %s", stock_code)
                    continue
                picking_type = warehouse.in_type_id
                
                # Chuyển refdate sang date (chỉ lấy ngày)
                misa_date = False
                if refdate_str:
                    try:
                        misa_date = datetime.fromisoformat(refdate_str.replace('Z', '+00:00')).date()
                    except Exception:
                        misa_date = False

                po_vals = {
                    "partner_id": partner.id,
                    "origin": memo,
                    "picking_type_id": picking_type.id,
                    "name": refno,
                    "x_studio_misa_date": misa_date,
                    "x_studio_delivery_term": custom_field2 or False,
                    "x_studio_misa_purchase_status": misa_purchase_status or False,
                }

                if planned_naive_utc:
                    po_vals["date_planned"] = planned_naive_utc 

                po_rec = self.env["purchase.order"].create(po_vals)


                for line in lines:
                    code = line.get("inventory_item_code", "unknown_code").strip()
                    name = line.get("description", "unknown product").strip()
                    qty = float(line.get("quantity", 1))
                    price = float(line.get("unit_price", 0))
                    unit_name = line.get("unit_name", "Cái").strip()
                    vat_rate = float(line.get("vat_rate", 0))
                    
                    tax_ids = self._tax_ids_from_misa_line(line)

                    product = odoo_utils._get_or_create_product(
                        code=code,
                        name=name,
                        unit_name=unit_name,
                        cost=price,
                        purchase_ok=True,
                        sale_ok=True
                    )

                    qty_base, price_base, is_default = self._convert_qty_price_to_default_uom(product, unit_name, qty, price, code, crm_headers)
                    pol_vals = {
                        "order_id": po_rec.id,
                        "name": name,
                        "product_id": product.id,
                        "product_qty": qty_base,
                        "product_uom": product.uom_id.id,
                        "price_unit": price_base,
                        "taxes_id": [(6, 0, tax_ids)]
                    }
                    
                    if planned_naive_utc:
                        pol_vals["date_planned"] = planned_naive_utc  


                    
                    self.env["purchase.order.line"].create(pol_vals)
                    
                    
                po_rec.write({'partner_ref': refno})      # tham chiếu NCC, dễ tra cứu
                po_rec.button_confirm()                   # xác nhận đơn mua

                # Cập nhật ngày dự kiến + đảm bảo receipt đúng kho/location
                for picking in po_rec.picking_ids:
                    if planned_naive_utc:
                        picking.scheduled_date = planned_naive_utc
                    # dùng đúng picking type của warehouse đã map
                    if picking.picking_type_id.id != picking_type.id:
                        picking.picking_type_id = picking_type.id
                    # (tuỳ chọn) ép đích nhập về đúng location kho đã map
                    if location:
                        picking.location_dest_id = location.id
                        for move in picking.move_ids_without_package:
                            move.location_dest_id = location.id
            page_index += 1
