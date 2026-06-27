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
        """
        if not po_code:
            return None
        
        misa_utils = self.env['misa.api.utils']
        
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
        
        payload = {
            "sort": "[{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":4008,\"desc\":true,\"data_type\":1,\"operand\":1}]",
            "filter": [
                {
                    "property": 3972,
                    "value": "2024-01-01T00:00:00.00Z",
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
            "loadMode": 2
        }
        
        _logger.info("🔍 Tìm kiếm đơn %s trong MISA với customFilter...", po_code)
        
        response = misa_utils._fetch_with_retry(
            "https://actapp.misa.vn/g2/api/pu/v1/pu_order/paging_filter_v2",
            headers, payload
        )
        
        if response.status_code != 200:
            _logger.error("❌ Không thể gọi API MISA: %s", response.status_code)
            return None
        
        response_data = response.json()
        data = response_data.get("Data", {})
        page_data = data.get("PageData", [])
        
        if not page_data:
            total = data.get("Total", 0)
            _logger.warning("⚠️ Không tìm thấy đơn %s trong MISA (PageData rỗng, Total=%s)", po_code, total)
            return None
        
        found_po = page_data[0]
        _logger.info("✅ Tìm thấy đơn %s trong MISA (refid: %s)", po_code, found_po.get("refid"))
        return found_po

    def _misa_get_product_id_by_code(self, product_code, product_name, crm_headers):
        """Gọi API DataPaging để lấy ProductID từ ProductCode."""
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
        """Lấy quy đổi UoM từ MISA"""
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
        """Chuyển đổi qty/price về đơn vị mặc định"""
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

    def _prepare_misa_po_line_vals(self, line, po_rec, planned_naive_utc, crm_headers, odoo_utils):
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

        return {
            "order_id": po_rec.id,
            "name": name,
            "product_id": product.id,
            "product_qty": qty_base,
            "product_uom": product.uom_id.id,
            "price_unit": price_base,
            "taxes_id": [(6, 0, tax_ids)],
            "date_planned": planned_naive_utc or fields.Datetime.now(),
        }

    def _update_received_po_from_misa(self, po_rec, lines, planned_naive_utc, crm_headers, odoo_utils):
        """Update PO da co receipt done ma khong cancel/unlink cac dong da nhan."""
        line_model = self.env["purchase.order.line"].sudo()
        lines_by_code = {}
        for po_line in po_rec.order_line:
            code = (po_line.product_id.default_code or "").strip().upper()
            if code:
                lines_by_code.setdefault(code, []).append(po_line)

        updated_count = 0
        created_count = 0
        skipped_qty_count = 0

        for misa_line in lines:
            vals = self._prepare_misa_po_line_vals(
                misa_line, po_rec, planned_naive_utc, crm_headers, odoo_utils
            )
            product = self.env["product.product"].browse(vals["product_id"])
            code = (product.default_code or "").strip().upper()
            po_line = code and lines_by_code.get(code) and lines_by_code[code].pop(0)

            if po_line:
                write_vals = {
                    "name": vals["name"],
                    "price_unit": vals["price_unit"],
                    "taxes_id": vals["taxes_id"],
                    "date_planned": vals["date_planned"],
                }
                if vals["product_qty"] >= po_line.qty_received:
                    write_vals["product_qty"] = vals["product_qty"]
                else:
                    skipped_qty_count += 1
                    _logger.warning(
                        "Skip quantity update for PO %s line %s: MISA qty %s < received qty %s",
                        po_rec.name,
                        po_line.display_name,
                        vals["product_qty"],
                        po_line.qty_received,
                    )
                po_line.sudo().write(write_vals)
                updated_count += 1
            else:
                line_model.create(vals)
                created_count += 1

        extra_received = sum(
            1
            for remaining_lines in lines_by_code.values()
            for po_line in remaining_lines
            if po_line.qty_received
        )
        if extra_received:
            _logger.warning(
                "PO %s has %s received lines not present in MISA; kept them unchanged.",
                po_rec.name,
                extra_received,
            )

        return updated_count, created_count, skipped_qty_count

    def _get_or_create_vn_vat(self, rate, use='purchase'):
        """Lấy hoặc tạo thuế VAT"""
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
        """Xác định thuế từ dòng MISA"""
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
        """Wizard action: gọi lõi _sync_po_core rồi bọc ra display_notification (UI)."""
        if not self.po_code or not self.po_code.strip():
            raise models.UserError("⚠️ Vui lòng nhập mã đơn hàng")

        result = self._sync_po_core(self.po_code, delete_when_missing=True)

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

    def _safe_delete_po(self, odoo_po, po_code):
        """
        Helper: Xóa PO an toàn theo logic của SO (giống action_resync_from_misa_hard).
        Trả về dict {'ok': bool, 'error': str or None}
        """
        try:
            # Sử dụng sudo() và with_context để bypass permissions
            odoo_po = odoo_po.sudo().with_context(force_delete=True)
            
            # Step 1: Kiểm tra điều kiện không cho phép xóa
            if any(inv.state == 'posted' for inv in odoo_po.invoice_ids):
                return {
                    'ok': False, 
                    'error': 'cannot_delete', 
                    'message': f'Không thể xóa {po_code} vì có invoice đã ghi sổ'
                }
            
            if any(pick.state == 'done' for pick in odoo_po.picking_ids):
                return {
                    'ok': False, 
                    'error': 'cannot_delete', 
                    'message': f'Không thể xóa {po_code} vì có phiếu nhập đã hoàn thành'
                }
            
            _logger.info("🔧 Bắt đầu xóa PO %s (state=%s)", po_code, odoo_po.state)
            
            # Step 2: Xóa invoices (draft) - với context để bypass constraint
            for invoice in odoo_po.invoice_ids.filtered(lambda inv: inv.state == 'draft'):
                try:
                    invoice.with_context(force_delete=True).unlink()
                    _logger.info("  ✓ Đã xóa invoice draft: %s", invoice.name)
                except Exception as inv_err:
                    _logger.warning("  ⚠️ Không thể xóa invoice %s: %s", invoice.name, inv_err)
            
            # Step 3: Cancel invoices khác (không phải draft/posted)
            for invoice in odoo_po.invoice_ids.filtered(lambda inv: inv.state not in ('draft', 'cancel', 'posted')):
                try:
                    if hasattr(invoice, 'button_cancel'):
                        invoice.button_cancel()
                    elif hasattr(invoice, 'action_cancel'):
                        invoice.action_cancel()
                    _logger.info("  ✓ Đã cancel invoice: %s", invoice.name)
                except Exception as inv_err:
                    _logger.warning("  ⚠️ Không thể cancel invoice %s: %s", invoice.name, inv_err)
            
            # Step 4: Xử lý pickings
            _logger.info("  📦 Xử lý %s pickings...", len(odoo_po.picking_ids))
            picks_to_delete = []
            
            for p in odoo_po.picking_ids:
                if p.state == 'done':
                    _logger.info("    ⊗ Giữ picking done: %s", p.name)
                    continue
                
                # Reset qty_done trên move_lines
                for ml in p.move_line_ids:
                    if ml.qty_done:
                        ml.with_context(force_delete=True).write({'qty_done': 0})
                
                # Unreserve moves
                for mv in p.move_ids_without_package.filtered(lambda m: m.state not in ('done', 'cancel')):
                    try:
                        if hasattr(mv, '_do_unreserve'):
                            mv._do_unreserve()
                        elif hasattr(mv, 'do_unreserve'):
                            mv.do_unreserve()
                    except Exception as e:
                        _logger.debug("    Unreserve move failed: %s", e)
                
                # Cancel moves
                for mv in p.move_ids_without_package.filtered(lambda m: m.state not in ('done', 'cancel')):
                    try:
                        if hasattr(mv, '_action_cancel'):
                            mv._action_cancel()
                        else:
                            mv.action_cancel()
                    except Exception as e:
                        _logger.debug("    Cancel move failed: %s", e)
                
                # Cancel picking
                if p.state != 'cancel':
                    try:
                        if hasattr(p, 'button_cancel'):
                            p.button_cancel()
                        else:
                            p.action_cancel()
                        _logger.info("    ✓ Đã cancel picking: %s", p.name)
                    except Exception as e:
                        _logger.warning("    ⚠️ Cancel picking %s failed: %s", p.name, e)
                        # Fallback: force cancel bằng write
                        try:
                            p.with_context(force_delete=True).write({'state': 'cancel'})
                        except Exception as e2:
                            _logger.error("    ✗ Force cancel failed: %s", e2)
                
                picks_to_delete.append(p)
            
            # Step 5: Cancel PO
            _logger.info("  🛒 Cancel PO...")
            if odoo_po.state not in ('cancel', 'draft'):
                try:
                    odoo_po.button_cancel()
                    _logger.info("    ✓ Đã cancel PO bằng button_cancel()")
                except Exception as e:
                    _logger.warning("    ⚠️ button_cancel failed: %s → Thử fallback", e)
                    # Fallback 1: cancel lines
                    try:
                        for line in odoo_po.order_line:
                            if hasattr(line, '_action_cancel'):
                                line._action_cancel()
                        odoo_po.write({'state': 'cancel'})
                        _logger.info("    ✓ Đã cancel PO bằng fallback (cancel lines + write)")
                    except Exception as e2:
                        _logger.error("    ✗ Fallback cancel failed: %s", e2)
                        # Fallback 2: force write state
                        try:
                            odoo_po.with_context(force_delete=True).write({'state': 'cancel'})
                            _logger.info("    ✓ Đã force cancel PO bằng write")
                        except Exception as e3:
                            return {'ok': False, 'error': 'cancel_failed', 'message': f'Không thể cancel PO: {e3}'}
            
            # Refresh cache
            self.env.invalidate_all()
            odoo_po = odoo_po.sudo().browse(odoo_po.id)
            
            _logger.info("  🔍 Trạng thái PO sau cancel: %s", odoo_po.state)
            
            # Step 6: Xóa pickings
            for p in picks_to_delete:
                try:
                    p.with_context(force_delete=True).unlink()
                    _logger.info("    ✓ Đã xóa picking: %s", p.name)
                except Exception as e:
                    _logger.warning("    ⚠️ Không xóa được picking %s: %s", p.name, e)
            
            # Step 7: Xóa invoices còn lại
            for inv in odoo_po.invoice_ids.filtered(lambda i: i.state in ('draft', 'cancel')):
                try:
                    inv.with_context(force_delete=True).unlink()
                    _logger.info("    ✓ Đã xóa invoice: %s", inv.name)
                except Exception as e:
                    _logger.warning("    ⚠️ Không xóa được invoice %s: %s", inv.name, e)
            
            # Step 8: Xóa order lines
            _logger.info("  📋 Xóa %s order lines...", len(odoo_po.order_line))
            try:
                odoo_po.order_line.with_context(force_delete=True).unlink()
                _logger.info("    ✓ Đã xóa tất cả order lines")
            except Exception as line_err:
                _logger.warning("    ⚠️ Không thể xóa order lines: %s", line_err)
            
            # Step 9: Đảm bảo state=cancel (không dùng draft vì PO yêu cầu phải cancel mới xóa được)
            if odoo_po.state != 'cancel':
                try:
                    odoo_po.with_context(force_delete=True).write({'state': 'cancel'})
                    _logger.info("  ✓ Đã set state=cancel")
                except Exception as e:
                    _logger.error("  ✗ Không thể set cancel: %s", e)
            
            # Refresh lại một lần nữa
            self.env.invalidate_all()
            odoo_po = odoo_po.sudo().browse(odoo_po.id)
            
            # Step 10: Xóa PO với bypass constraint
            _logger.info("  🗑️ Xóa PO (state=%s)...", odoo_po.state)
            try:
                # Bypass thêm constraint check
                odoo_po.with_context(
                    force_delete=True,
                    disable_cancel_warning=True,
                    bypass_cancel_check=True,
                    skip_check=True
                ).unlink()
                _logger.info("✅ Đã xóa PO %s thành công!", po_code)
                return {'ok': True}
            except Exception as e:
                _logger.error("❌ Lỗi khi unlink PO (state=%s): %s", odoo_po.state, e)
                
                # Fallback cuối: Thử xóa trực tiếp bằng SQL (unsafe nhưng đảm bảo xóa được)
                try:
                    _logger.warning("  ⚠️ Thử xóa trực tiếp bằng SQL...")
                    self.env.cr.execute("DELETE FROM purchase_order WHERE id = %s", (odoo_po.id,))
                    _logger.info("✅ Đã xóa PO %s bằng SQL!", po_code)
                    return {'ok': True}
                except Exception as sql_err:
                    _logger.error("❌ Lỗi xóa bằng SQL: %s", sql_err)
                    return {'ok': False, 'error': 'unlink_failed', 'message': f'Không thể unlink: {e}'}
            
        except Exception as e:
            _logger.exception("❌ Lỗi tổng thể khi xoá PO %s: %s", po_code, e)
            return {'ok': False, 'error': 'delete_failed', 'message': str(e)}

    def _create_or_update_po(self, misa_po, odoo_po, headers, crm_headers, misa_utils, odoo_utils):
        """Tạo mới hoặc cập nhật PO"""
        def _to_naive_utc(dt_str: str):
            if not dt_str:
                return False
            aware = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            return aware.astimezone(timezone.utc).replace(tzinfo=None)

        refid = misa_po.get("refid")
        supplier_name = misa_po.get("account_object_name")
        refno = misa_po.get("refno", "PO-MISA")
        memo = misa_po.get("journal_memo", "")
        refdate_str = misa_po.get("refdate")  # ngày chứng từ
        custom_field2 = misa_po.get("custom_field2", "")  # điều khoản giao hàng
        receive_date_str = misa_po.get("receive_date") or refdate_str
        planned_naive_utc = _to_naive_utc(receive_date_str)
        custom_field1 = misa_po.get("custom_field1", "")  # điều khoản giao hàng
        receive_address = misa_po.get("receive_address", "")  # địa chỉ nhận hàng
        misa_purchase_status = misa_po.get("custom_field10", "")  # trạng thái đơn mua hàng từ MISA

        # Chuyển refdate sang date (chỉ lấy ngày)
        misa_date = False
        if refdate_str:
            try:
                misa_date = datetime.fromisoformat(refdate_str.replace('Z', '+00:00')).date()
            except Exception:
                misa_date = False

        partner = odoo_utils._get_or_create_partner(supplier_name)

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
            "pageIndex": 1,
            "pageSize": 200,
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

        # stock_code = lines[0].get("stock_code", "").strip().replace(" ", "").upper()
        stock_code = lines[0].get("custom_field5", "").strip().replace(" ", "").upper()

        
        
        stock_mapping = {
                "HCM": "TSN/Stock",
                "BENCAM": "KBC/Tồn kho/KỆ NHẬP CHỜ GIAO",
                "HIENDUC": "KHD/Tồn kho",
                "HCM_SHOWROOM": "TSNSR/Stock",
                "HLV":"HLV/Stock",
                "BẾN CAM": "KBC/Tồn kho/KỆ NHẬP CHỜ GIAO",
                "BẾNCAM": "KBC/Tồn kho/KỆ NHẬP CHỜ GIAO",
                "HIỀN ĐỨC": "KHD/Tồn kho",
                "ĐÀ NẴNG": "KDN/Tồn kho",
                "ĐÀNẴNG": "KDN/Tồn kho",
                "HIỀNĐỨC": "KHD/Tồn kho",
                "HIENDUC": "KHD/Tồn kho",
                "DANANG": "KDN/Tồn kho",
                "TSNSR": "TSNSR/Stock",
                "TSN SHOWROOM": "TSNSR/Stock",
                "TSNSHOWROOM": "TSNSR/Stock",
            }

        if stock_code not in stock_mapping:
            # raise models.UserError(f"📛 Kho {stock_code} không được hỗ trợ")
            stock_code = "BENCAM" #default về BENCAM nếu không tìm thấy, vì đa số là BENCAM, tránh lỗi không đồng bộ được PO chỉ vì mã kho không chuẩn (thường do nhập liệu từ MISA)

        location_name = stock_mapping[stock_code]
        location = self.env['stock.location'].search([('complete_name', '=', location_name)], limit=1)

        if not location:
            raise models.UserError(f"❌ Không tìm thấy location {location_name}")

        warehouse = False
        curr_loc = location
        while curr_loc and not warehouse:
            warehouse = self.env['stock.warehouse'].search([
                ('view_location_id', '=', curr_loc.id)
            ], limit=1)
            curr_loc = curr_loc.location_id

        if not warehouse:
            raise models.UserError(f"❌ Không tìm thấy warehouse cho {stock_code}")

        picking_type = warehouse.in_type_id

        po_header_vals = {
            'partner_id': partner.id,
            'origin': memo,
            'picking_type_id': picking_type.id,
            'date_planned': planned_naive_utc or fields.Datetime.now(),
            'partner_ref': refno,
            'x_studio_misa_date': misa_date,
            'x_studio_delivery_term': custom_field2 or False,
            "x_studio_iu_kin_thanh_ton": custom_field1 or False,
            'x_studio_ddgh': receive_address or False,
            'x_studio_misa_purchase_status': misa_purchase_status or False,
        }
        lines_already_synced = False

        # Update or create PO
        if odoo_po:
            _logger.info("Dong bo lai PO %s tu MISA", refno)
            has_done_receipt = any(picking.state == 'done' for picking in odoo_po.picking_ids)

            if has_done_receipt:
                _logger.info(
                    "PO %s has done receipts; update header/lines in place without cancel/unlink.",
                    refno,
                )
                odoo_po.write(po_header_vals)
                po_rec = odoo_po
                updated_count, created_count, skipped_qty_count = self._update_received_po_from_misa(
                    po_rec, lines, planned_naive_utc, crm_headers, odoo_utils
                )
                lines_already_synced = True
                total_lines = len(lines)
                message = (
                    'Da cap nhat an toan: %s (%s dong MISA, update %s, tao moi %s, bo qua qty %s)'
                    % (refno, total_lines, updated_count, created_count, skipped_qty_count)
                )
                title = 'Cap nhat thanh cong'
            else:
                need_reconfirm = False
                if odoo_po.state not in ('draft', 'sent', 'cancel'):
                    _logger.info("PO %s dang o trang thai %s -> cancel truoc khi cap nhat", refno, odoo_po.state)
                    odoo_po.button_cancel()
                    need_reconfirm = True

                for picking in odoo_po.picking_ids:
                    if picking.state not in ('done', 'cancel'):
                        picking.action_cancel()

                if odoo_po.state == 'cancel':
                    odoo_po.button_draft()

                odoo_po.order_line.unlink()
                odoo_po.write(po_header_vals)

                po_rec = odoo_po
                total_lines = len(lines)
                message = f'Da dong bo: {refno} ({total_lines} dong)'
                title = 'Cap nhat thanh cong'
        else:
            _logger.info("Tao moi PO %s tu MISA", refno)
            po_vals = dict(po_header_vals, name=refno)
            # Skip Zalo notification during creation (because no lines yet)
            po_rec = self.env["purchase.order"].with_context(skip_zalo_po_create=True).create(po_vals)
            total_lines = len(lines)
            message = f'Da tao: {refno} ({total_lines} dong)'
            title = 'Tao moi thanh cong'
        if not lines_already_synced:
            for line in lines:
                pol_vals = self._prepare_misa_po_line_vals(
                    line, po_rec, planned_naive_utc, crm_headers, odoo_utils
                )
                self.env["purchase.order.line"].create(pol_vals)
        if po_rec.state == 'draft':
            po_rec.button_confirm()

        for picking in po_rec.picking_ids:
            if lines_already_synced and picking.state == 'done':
                continue
            if planned_naive_utc:
                picking.scheduled_date = planned_naive_utc
            if picking.picking_type_id.id != picking_type.id:
                picking.picking_type_id = picking_type.id
            if location:
                picking.location_dest_id = location.id
                for move in picking.move_ids_without_package:
                    move.location_dest_id = location.id
        # Trigger Zalo Notification manually after lines are added (for new POs)
        # Check if it was a new creation (not update) - based on logic above, update uses write()
        if not odoo_po and hasattr(po_rec, '_send_zalo_new_po_notification'):
            try:
                _logger.info("Triggering Zalo PO Notification for synced PO %s", po_rec.name)
                po_rec._send_zalo_new_po_notification()
            except Exception as e:
                 _logger.exception("Error sending Zalo PO Notification for %s: %s", po_rec.name, e)

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

    def _sync_po_core(self, po_code, *, delete_when_missing=True, create_when_missing=True):
        """
        Lõi đồng bộ: trả về JSON dict để API dùng được và wizard cũng có thể wrap thành notification.
        Logic tương đồng với SO sync:
        - Không có trong MISA + Có trong Odoo + delete_when_missing=True → XÓA
        - Không có trong MISA + Không có trong Odoo → NOT_FOUND
        - Có trong MISA + Có trong Odoo → CẬP NHẬT
        - Có trong MISA + Không có trong Odoo + create_when_missing=True → TẠO MỚI
        - Có trong MISA + Không có trong Odoo + create_when_missing=False → NOT_ALLOWED
        """
        if not po_code or not po_code.strip():
            return {'ok': False, 'error': 'missing_po_code', 'message': '⚠️ Thiếu mã đơn hàng'}

        po_code = po_code.strip()

        misa_utils  = self.env['misa.api.utils']
        odoo_utils  = self.env['odoo.utils']
        misa_config = self.env['misa.config']

        try:
            access_token = misa_utils._get_misa_token()
            headers      = misa_config.get_default_headers(access_token)
            crm_headers  = misa_utils._get_cached_crm_headers()
        except Exception as e:
            _logger.exception("❌ Lỗi token/headers: %s", e)
            return {'ok': False, 'error': 'auth_failed', 'message': str(e)}

        misa_po = self._search_po_in_misa(po_code, headers)
        odoo_po = self.env["purchase.order"].search([
                ('name', '=', po_code)
            ], limit=1)
        # ===== CASE 1: Không có trong MISA =====
        if not misa_po:
            if odoo_po:
                if delete_when_missing:
                    _logger.warning("🗑️ Xoá PO %s vì không tồn tại trong MISA", po_code)
                    
                    # Gọi helper xóa an toàn (giống SO logic)
                    delete_result = self._safe_delete_po(odoo_po, po_code)
                    
                    if delete_result['ok']:
                        return {
                            'ok': True,
                            'action': 'deleted',
                            'name': po_code,
                            'res_id': None,
                            'detail': f'Đơn {po_code} đã xoá (không tồn tại trong MISA)'
                        }
                    else:
                        return {
                            'ok': False,
                            'error': delete_result.get('error', 'delete_failed'),
                            'message': delete_result.get('message', 'Không thể xóa PO')
                        }
                else:
                    return {
                        'ok': True,
                        'action': 'orphaned',
                        'name': po_code,
                        'res_id': odoo_po.id,
                        'detail': f'Đơn {po_code} tồn tại trong Odoo nhưng không còn trong MISA'
                    }
            else:
                return {
                    'ok': False,
                    'action': 'not_found',
                    'name': po_code,
                    'res_id': None,
                    'detail': f'Không tìm thấy {po_code} trong MISA'
                }
        
        # ===== CASE 2: Có trong MISA =====
        else:
            if not odoo_po and not create_when_missing:
                return {
                    'ok': False,
                    'action': 'not_allowed',
                    'error': 'create_not_allowed',
                    'name': po_code,
                    'res_id': None,
                    'detail': f'Không cho phép tạo mới đơn {po_code} (create_when_missing=False)'
                }
            
            try:
                existed = bool(odoo_po)
                
                result = self.sudo()._create_or_update_po(
                    misa_po, odoo_po, headers, crm_headers, misa_utils, odoo_utils
                )
                
                after_po = odoo_po or self.env["purchase.order"].search([
                    ('name', '=', po_code)
                ], limit=1)
                
                return {
                    'ok': True,
                    'action': 'updated' if existed else 'created',
                    'res_id': after_po.id if after_po else None,
                    'name': after_po.name if after_po else po_code,
                    'detail': f'Đã {"cập nhật" if existed else "tạo mới"} đơn {po_code} từ MISA'}
            except Exception as e:
                _logger.exception("❌ Lỗi upsert PO %s: %s", po_code, e)
                return {
                    'ok': False,
                    'error': 'update_failed' if existed else 'create_failed',
                    'message': str(e)
                }


# ===================== EXTEND PurchaseOrder với API =====================
class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    @api.model
    def api_sync_po_by_code(self, po_code, create_when_missing=True, delete_when_missing=True):
        """
        Public API (RPC/JSON-RPC) để đồng bộ PO theo mã đơn từ MISA.
        """
        po_code = (str(po_code or '')).strip()
        if not po_code:
            return {'ok': False, 'error': 'missing_po_code', 'message': 'Thiếu mã đơn hàng'}
        
        try:
            sync_wizard = self.env['misa.po.sync'].sudo().create({'po_code': po_code})
            
            result = sync_wizard._sync_po_core(
                po_code,
                delete_when_missing=delete_when_missing,
                create_when_missing=create_when_missing
            )
            
            return result
        except Exception as e:
            _logger.exception("❌ API sync PO lỗi: %s", e)
            return {'ok': False, 'error': 'exception', 'message': str(e)}
        
        
        
        
class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # ======================================================================
    # SQL CONSTRAINT: Chốt chặn chống trùng name
    # ======================================================================
    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Mã đơn mua hàng (Name) đã tồn tại! Vui lòng kiểm tra lại.'),
    ]
