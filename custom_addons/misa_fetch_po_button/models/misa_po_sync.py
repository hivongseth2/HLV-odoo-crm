from odoo import models, fields, api, _
import logging
from datetime import datetime, timezone
import uuid
import requests


_logger = logging.getLogger(__name__)


class MisaPOSync(models.TransientModel):
    _name = "misa.po.sync"
    _description = "MISA PO Sync by Code"
    
    po_code = fields.Char(
        string="Mã đơn hàng", 
        required=True,
        help="Nhập mã đơn hàng cần đồng bộ (ví dụ: DMH12218)"
    )

    def _search_po_in_misa(self, po_code: str, headers):
        """
        Tìm kiếm đơn PO trong MISA theo mã đơn sử dụng customFilter
        Workflow:
        1. Gọi paging_filter_v2 với customFilter chứa mã đơn
        2. Nếu có kết quả → đơn tồn tại trong MISA
        3. Nếu không có kết quả → đơn không tồn tại
        """
        if not po_code:
            return None
        
        misa_utils = self.env['misa.api.utils']
        
        # Build customFilter theo đúng format MISA
        custom_filter = [{
            "property": 4008,
            "value": po_code,
            "operator": 1,
            "operand": 1,
            "childrens": [
                {"property": 57, "value": po_code, "operator": 1, "operand": 2, "data_type": 1},
                {"property": 2656, "value": po_code, "operator": 1, "operand": 2, "data_type": 1},
                {"property": 4030, "value": po_code, "operator": 1, "operand": 2}
            ],
            "data_type": 1
        }]
        
        # Payload tìm kiếm theo mã đơn
        payload = {
            "sort": "[{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":4008,\"desc\":true,\"data_type\":1,\"operand\":1}]",
            "filter": [
                {
                    "property": 3972,
                    "value": "2024-01-01T00:00:00.00Z",  # Từ 2024 để lấy đủ dữ liệu
                    "operator": 10,
                    "operand": 1,
                    "data_type": 3
                },
                {
                    "property": 3972,
                    "value": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    "operator": 12,
                    "operand": 1,
                    "data_type": 3
                }
            ],
            "customFilter": custom_filter,
            "pageIndex": 1,
            "pageSize": 20,
            "useSp": False,
            "view": 2,
            "summaryColumns": [5039, 5104, 247],
            "loadMode": 2  # loadMode = 2 (KHÔNG phải 3)
        }
        
        _logger.info("🔍 Tìm kiếm đơn %s trong MISA với customFilter...", po_code)
        
        response = misa_utils._fetch_with_retry(
            "https://actapp.misa.vn/g2/api/pu/v1/pu_order/paging_filter_v2",  # API đúng
            headers, payload
        )
        
        if response.status_code != 200:
            _logger.error("❌ Không thể gọi API MISA: %s", response.status_code)
            return None
        
        response_data = response.json()
        data = response_data.get("Data", {})
        
        # QUAN TRỌNG: Kiểm tra PageData TRƯỚC, không dựa vào Total
        # Vì MISA có thể trả Total=0 nhưng vẫn có PageData
        page_data = data.get("PageData", [])
        
        if not page_data:
            total = data.get("Total", 0)
            _logger.warning("⚠️ Không tìm thấy đơn %s trong MISA (PageData rỗng, Total=%s)", po_code, total)
            return None
        
        # Lấy đơn đầu tiên (vì filter theo mã nên chỉ có 1 kết quả)
        found_po = page_data[0]
        _logger.info("✅ Tìm thấy đơn %s trong MISA (refid: %s)", po_code, found_po.get("refid"))
        return found_po

    def _misa_get_product_id_by_code(self, product_code, product_name, crm_headers):
        """
        Gọi API DataPaging để lấy ProductID từ ProductCode.
        """
        if not product_code:
            return None
        
        url = "https://amisapp.misa.vn/crm/g2/api/business/Product/Grid"
        
        payload = {
            "Columns": "SUQsUHJvZHVjdENvZGUsUHJvZHVjdE5hbWUsUHJvZHVjdENhdGVnb3J5SUQsUHJvZHVjdENhdGVnb3J5SURUZXh0LFVzYWdlVW5pdElELFVzYWdlVW5pdElEVGV4dCxVbml0UHJpY2UsVGF4SUQsVGF4SURUZXh0LElzU2V0UHJvZHVjdCxGb3JtTGF5b3V0SUQsRm9ybUxheW91dElEVGV4dCxPd25lcklELE93bmVySURUZXh0LElzU3lzdGVtLEF2YXRhcg==",
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
        Lấy quy đổi UoM từ MISA
        """
        if not product_code:
            return []

        product_id = self._misa_get_product_id_by_code(product_code, None, crm_headers)
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
            resp = requests.post(url, headers=crm_headers, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return data.get("Data", []) or []
        except Exception as e:
            _logger.exception("Lỗi gọi Product/DataSubPaging: %s", e)
            return []

    def _convert_qty_price_to_default_uom(self, product, misa_uom_text, qty, price, misa_product_code, crm_headers):
        """
        Chuyển đổi qty/price về đơn vị mặc định
        """
        default_uom_name = (product.uom_id and product.uom_id.name) or ""
        if not misa_uom_text or misa_uom_text.strip().lower() == default_uom_name.strip().lower():
            return qty, price, True

        conversions = self._misa_fetch_conversion_units(misa_product_code, crm_headers) if misa_product_code else []
        conv = next((
            c for c in (conversions or [])
            if (c.get("ConversionUnitIDText") or "").strip().lower() == misa_uom_text.strip().lower()
        ), None)

        if not conv:
            _logger.warning("⚠️ Không tìm thấy mapping UoM cho '%s'", misa_uom_text)
            return qty, price, False

        try:
            rate = float(conv.get("ConversionRate") or 0) or 0.0
        except Exception:
            rate = 0.0
        try:
            op_id = int(conv.get("ConversionOperatorID") or 1)
        except Exception:
            op_id = 1

        if rate <= 0:
            _logger.warning("⚠️ ConversionRate không hợp lệ cho '%s'", misa_uom_text)
            return qty, price, False

        if op_id == 1:
            qty_base = qty * rate
            price_base = price / rate if rate else price
        else:
            qty_base = qty / rate
            price_base = price * rate

        return qty_base, price_base, False

    def _get_or_create_vn_vat(self, rate, use='purchase'):
        """
        Lấy hoặc tạo thuế VAT
        """
        Tax = self.env['account.tax'].with_company(self.env.company)
        TaxGroup = self.env['account.tax.group'].with_company(self.env.company)

        rate = float(rate)

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

        tax = Tax.search([
            ('type_tax_use', '=', use),
            ('amount_type', '=', 'percent'),
            ('amount', '=', rate),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if tax:
            return tax

        rate_str = str(int(rate)) if float(rate).is_integer() else str(rate)
        return Tax.create({
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

    def _tax_ids_from_misa_line(self, line):
        """
        Xác định thuế từ dòng MISA
        """
        kct_markers = {'KCT', 'KHONGCHIU', 'NO_VAT', -1, -2}
        raw_rate = line.get('vat_rate', None)
        is_not_vat = str(line.get('is_not_vat', '')).lower() in ('1', 'true', 'yes')
        
        if is_not_vat or raw_rate in kct_markers:
            return []
        if raw_rate in (None, '', 'null'):
            return []
        
        try:
            rate = float(raw_rate)
        except Exception:
            return []
        
        if abs(rate) < 1e-9:
            tax = self._get_or_create_vn_vat(0.0, use='purchase')
            return [tax.id] if tax else []
        
        tax = self._get_or_create_vn_vat(rate, use='purchase')
        return [tax.id] if tax else []

    def action_sync_po(self):
        """
        Wizard action: gọi lõi _sync_po_core rồi bọc ra display_notification (UI).
        """
        if not self.po_code or not self.po_code.strip():
            raise models.UserError("⚠️ Vui lòng nhập mã đơn hàng")

        result = self._sync_po_core(self.po_code, delete_when_missing=True)

        # Map JSON -> UI notification
        title_map = {
            'created': '✅ Tạo mới thành công',
            'updated': '🔄 Cập nhật thành công',
            'deleted': '🗑️ Đã xoá',
            'not_found': 'ℹ️ Không tìm thấy',
        }
        notif_type = 'success' if result.get('ok') else ('warning' if result.get('action') in ('deleted', 'not_found') else 'danger')
        title = title_map.get(result.get('action'), 'Thông báo')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': result.get('detail') or result.get('message') or '',
                'type': notif_type,
                'sticky': False,
            }
        }


    def _create_or_update_po(self, misa_po, odoo_po, headers, crm_headers, misa_utils, odoo_utils):
        """
        Tạo mới hoặc cập nhật PO
        """
        def _to_naive_utc(dt_str: str):
            if not dt_str:
                return False
            aware = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            return aware.astimezone(timezone.utc).replace(tzinfo=None)

        # Lấy thông tin từ misa_po (PageData từ paging_filter_v2)
        refid = misa_po.get("refid")
        supplier_name = misa_po.get("account_object_name")
        refno = misa_po.get("refno", "PO-MISA")
        memo = misa_po.get("journal_memo", "")
        receive_date_str = misa_po.get("receive_date") or misa_po.get("refdate")
        planned_naive_utc = _to_naive_utc(receive_date_str)

        partner = odoo_utils._get_or_create_partner(supplier_name)

        # Lấy chi tiết đơn hàng từ API get_paging_detail
        detail_payload = {
            "columns": [2157, 1355, 2161, 4670, 5683, 5274, 3870, 3895, 5279, 308, 5364, 5350, 3404, 2358],
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
            "pageIndex": 1,
            "pageSize": 100,
            "sort": "[{\"property\":4555,\"desc\":false,\"data_type\":4,\"operand\":1}]",
            "summaryColumns": [3488, 3870, 3895, 3896, 308, 5350],
            "useSp": False,
            "view": 92
        }

        detail_res = misa_utils._fetch_with_retry(
            "https://actapp.misa.vn/g2/api/pu/v1/pu_order/get_paging_detail",
            headers, detail_payload
        )

        if detail_res.status_code != 200:
            raise models.UserError(f"❌ Không lấy được chi tiết PO {refno}")

        lines = detail_res.json().get("Data", {}).get("PageData", [])
        
        if not lines:
            raise models.UserError(f"⚠️ Đơn {refno} không có chi tiết sản phẩm")

        stock_code = lines[0].get("stock_code", "").strip().replace(" ", "").upper()
        
        stock_mapping = {
            "HCM": "TSN/Stock",
            "BENCAM": "KBC/Tồn kho",
            "HIENDUC": "KHD/Tồn kho",
            "HCM_SHOWROOM": "TSNSR/Stock"
        }

        if stock_code not in stock_mapping:
            raise models.UserError(f"📛 Kho {stock_code} không được hỗ trợ")

        location_name = stock_mapping[stock_code]
        location = self.env['stock.location'].search([('complete_name', '=', location_name)], limit=1)

        if not location:
            raise models.UserError(f"❌ Không tìm thấy location {location_name}")

        warehouse = self.env['stock.warehouse'].search([
            ('view_location_id', '=', location.location_id.id)
        ], limit=1)

        if not warehouse:
            raise models.UserError(f"❌ Không tìm thấy warehouse cho {stock_code}")

        picking_type = warehouse.in_type_id

        # CẬP NHẬT hoặc TẠO MỚI
        if odoo_po:
            _logger.info("🔄 Đồng bộ lại PO %s từ MISA", refno)
            
            # Hủy picking
            for picking in odoo_po.picking_ids:
                if picking.state not in ('done', 'cancel'):
                    picking.action_cancel()
            
            # Xóa dòng cũ
            odoo_po.order_line.unlink()
            
            # Cập nhật
            odoo_po.write({
                'partner_id': partner.id,
                'origin': memo,
                'picking_type_id': picking_type.id,
                'date_planned': planned_naive_utc or fields.Datetime.now(),
                'partner_ref': refno,
            })
            
            po_rec = odoo_po
            total_lines = len(lines)
            message = f'🔄 Đã đồng bộ: {refno} ({total_lines} dòng)'
            title = '🔄 Cập nhật thành công'
        else:
            _logger.info("✅ Tạo mới PO %s từ MISA", refno)
            po_vals = {
                "partner_id": partner.id,
                "origin": memo,
                "picking_type_id": picking_type.id,
                "name": refno,
                "date_planned": planned_naive_utc or fields.Datetime.now(),
                "partner_ref": refno,
            }
            po_rec = self.env["purchase.order"].create(po_vals)
            total_lines = len(lines)
            message = f'✅ Đã tạo: {refno} ({total_lines} dòng)'
            title = '✅ Tạo mới thành công'

        # Tạo dòng sản phẩm
        for line in lines:
            code = line.get("inventory_item_code", "unknown_code").strip()
            name = line.get("description", "unknown product").strip()
            qty = float(line.get("quantity", 1))
            price = float(line.get("unit_price", 0))
            unit_name = line.get("unit_name", "Cái").strip()
            
            tax_ids = self._tax_ids_from_misa_line(line)

            product = odoo_utils._get_or_create_product(
                code=code,
                name=name,
                unit_name=unit_name,
                cost=price,
                purchase_ok=True,
                sale_ok=True
            )

            qty_base, price_base, _ = self._convert_qty_price_to_default_uom(
                product, unit_name, qty, price, code, crm_headers
            )
            
            pol_vals = {
                "order_id": po_rec.id,
                "name": name,
                "product_id": product.id,
                "product_qty": qty_base,
                "product_uom": product.uom_id.id,
                "price_unit": price_base,
                "taxes_id": [(6, 0, tax_ids)],
                "date_planned": planned_naive_utc or fields.Datetime.now(),
            }
            
            self.env["purchase.order.line"].create(pol_vals)

        # Xác nhận
        if po_rec.state == 'draft':
            po_rec.button_confirm()

        # Cập nhật picking
        for picking in po_rec.picking_ids:
            if planned_naive_utc:
                picking.scheduled_date = planned_naive_utc
            if picking.picking_type_id.id != picking_type.id:
                picking.picking_type_id = picking_type.id
            if location:
                picking.location_dest_id = location.id
                for move in picking.move_ids_without_package:
                    move.location_dest_id = location.id

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': 'success',
                'sticky': False,
            }
        }
    def _sync_po_core(self, po_code: str, *, delete_when_missing: bool = True) -> dict:
        """
        Lõi đồng bộ: trả về JSON dict để API dùng được và wizard cũng có thể wrap thành notification.
        Hành vi giống hệt wizard:
        - Không có trong MISA + Có trong Odoo → (tuỳ chọn) XÓA
        - Có trong cả hai → CẬP NHẬT (upsert lines, không xoá cứng khi PO đã xác nhận)
        - Có trong MISA + Không có trong Odoo → TẠO MỚI
        """
        if not po_code or not po_code.strip():
            return {'ok': False, 'error': 'missing_po_code', 'message': '⚠️ Thiếu mã đơn hàng'}

        po_code = po_code.strip()

        misa_utils  = self.env['misa.api.utils']
        odoo_utils  = self.env['odoo.utils']
        misa_config = self.env['misa.config']

        # token + headers y hệt wizard
        try:
            access_token = misa_utils._get_misa_token()
            headers      = misa_config.get_default_headers(access_token)
            crm_token    = misa_utils._fetch_login_crm_token()
            crm_headers  = misa_config.get_crm_header(crm_token)
        except Exception as e:
            _logger.exception("❌ Lỗi token/headers: %s", e)
            return {'ok': False, 'error': 'auth_failed', 'message': str(e)}

        # tìm MISA + Odoo
        misa_po = self._search_po_in_misa(po_code, headers)
        odoo_po = self.env["purchase.order"].search([("name", "=", po_code)], limit=1)

        # Không có trong MISA
        if not misa_po:
            if odoo_po and delete_when_missing:
                try:
                    _logger.warning("🗑️ Xoá PO %s vì không tồn tại trong MISA", po_code)
                    if odoo_po.state not in ('draft', 'cancel'):
                        odoo_po.button_cancel()
                    odoo_po.unlink()
                    return {'ok': True, 'action': 'deleted', 'name': po_code, 'res_id': None,
                            'detail': f'Đơn {po_code} đã xoá (không tồn tại trong MISA)'}
                except Exception as e:
                    _logger.exception("❌ Lỗi khi xoá PO %s: %s", po_code, e)
                    return {'ok': False, 'error': 'delete_failed', 'message': str(e)}
            else:
                return {'ok': False, 'action': 'not_found', 'name': po_code, 'res_id': None,
                        'detail': f'Không tìm thấy {po_code} trong MISA'}

        # Có trong MISA → tạo mới/cập nhật đúng logic của wizard
        try:
            existed = bool(odoo_po)
            # Gọi cùng 1 hàm tạo/cập nhật như wizard (upsert lines, safe remove)
            _ = self._create_or_update_po(misa_po, odoo_po, headers, crm_headers, misa_utils, odoo_utils)
            # Lấy lại record sau khi upsert
            after_po = odoo_po or self.env["purchase.order"].search([("name", "=", po_code)], limit=1)
            return {
                'ok': True,
                'action': 'updated' if existed else 'created',
                'res_id': after_po.id if after_po else None,
                'name': after_po.name if after_po else po_code,
                'detail': f'Đã {"cập nhật" if existed else "tạo mới"} đơn {po_code} từ MISA'
            }
        except Exception as e:
            _logger.exception("❌ Lỗi upsert PO %s: %s", po_code, e)
            return {'ok': False, 'error': 'update_failed', 'message': str(e)}


# ===================== EXTEND PurchaseOrder với API =====================
class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.model
    def api_sync_po_by_code(self, po_code, create_when_missing=True):
        """
        API JSON (/api/misa/purchase_order/sync) — gọi chung lõi với wizard.
        - create_when_missing=True chỉ còn ý nghĩa nếu trong Odoo chưa có mà MISA có (thì sẽ tạo),
          còn nhánh 'không có trong MISA' thì việc xoá phụ thuộc delete_when_missing ở core (đang = True để giống wizard).
        """
        try:
            sync_wizard = self.env['misa.po.sync'].create({'po_code': po_code})
            # delete_when_missing=True để API mirror wizard 100%
            result = sync_wizard._sync_po_core(po_code, delete_when_missing=True)

            return result
        except Exception as e:
            _logger.exception("❌ API sync lỗi: %s", e)
            return {'ok': False, 'error': 'exception', 'message': str(e)}
