# models/sale_order_misa_sync.py
import requests
import logging
from odoo import models, fields, api, _
from dateutil.parser import parse as dtparse
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    misa_id = fields.Char(string="MISA ID")                  # ví dụ: "27264"
    misa_form_layout_id = fields.Integer(default=37)         # theo payload mẫu của bạn
    misa_form_type = fields.Integer(default=4)               # theo URL mẫu: .../SaleOrder/37/4

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
        if not js.get("Success"):
            raise ValueError(_("MISA trả về lỗi (FormDataNew): %s") % js)
        return js.get("Data", {}).get("CurrentData", {})

    def _misa_fetch_lines(self, misa_order_id):
        """Gọi DataSubPaging lấy các dòng sản phẩm (theo cách bạn đang dùng)."""
        self.ensure_one()
        misa_utils = self.env['misa.api.utils']
        misa_config = self.env['misa.config']
        headers, _ = self._misa_headers()

        # bạn đã có sẵn helper get_crm_sale_order_detail_payload + get_list_product_by_order_crm
        order_detail_url = "https://amisapp.misa.vn/crm/g2/api/business/SaleOrder/DataSubPaging"
        payload_detail = misa_config.get_crm_sale_order_detail_payload(misa_order_id)
        product_lines = misa_utils.get_list_product_by_order_crm(order_detail_url, headers, payload_detail)
        return product_lines or []

    # ---------------- core sync ----------------

    def action_sync_from_misa(self):
        """Nút bấm trong form SO: đồng bộ lại dữ liệu từ MISA."""
        self.ensure_one()
        odoo_utils = self.env['odoo.utils']

        # 1) Lấy header từ FormDataNew
        data = self._misa_fetch_order()
        # Một số key phổ biến cần dùng (tùy chỉnh theo thực tế):
        # DeliveryOrderNumber, SaleOrderNo, ListOrderNumber, AccountIDText, BookDate, DeliveryDate, BillingAddress, v.v.
        partner_name = data.get("AccountIDText") or data.get("BillingAccountIDText")
        order_no     = data.get("MISAOrderNo") or data.get("ListOrderNumber") or data.get("SaleOrderNo")
        delivery_no  = data.get("DeliveryOrderNumber") or order_no
        book_date    = data.get("BookDate") or data.get("InvoiceDate") or data.get("DeliveryDate")
        shipping_addr = data.get("BillingAddress")  # hoặc gọi API địa chỉ chi tiết của bạn

        # 2) Lấy lines từ DataSubPaging
        misa_order_id = data.get("ID") or data.get("CustomID") or self.misa_id
        lines = self._misa_fetch_lines(misa_order_id)

        # 3) Upsert header
        partner = odoo_utils._get_or_create_partner(partner_name or _("Khách hàng MISA"))
        vals_upd = {
            'partner_id': partner.id,
            'origin': order_no or (self.origin or self.name),
        }
        if book_date:
            try:
                vals_upd['date_order'] = dtparse(book_date).replace(tzinfo=None)
            except Exception:
                pass
        # Gán lại địa chỉ giao nếu bạn có helper build contact giao hàng
        try:
            delivery_contact = self.env['sale.api.import.wizard']._get_or_create_delivery_contact(
                parent_partner=partner,
                addr_str=shipping_addr or '',
                phone=data.get("Phone"),
                province_text=data.get("BillingProvinceIDText") or data.get("ShippingProvinceIDText")
            )
            vals_upd['partner_shipping_id'] = delivery_contact.id
        except Exception as e:
            _logger.warning("Không set được delivery contact: %s", e)

        self.write(vals_upd)

        # 4) Upsert lines theo product_code
        SaleLine = self.env['sale.order.line']
        lines_by_code = {}
        for l in self.order_line:
            code = (l.product_id and l.product_id.default_code) or ''
            if code:
                lines_by_code[code] = l

        seen_codes = set()

        def _flt(x, dv=0.0):
            try:
                return float(x or 0.0)
            except Exception:
                return dv

        for ln in lines:
            product_code   = ln.get("ProductIDText")
            description    = ln.get("Description") or product_code
            qty            = _flt(ln.get("Amount"), 0.0)
            price_unit     = _flt(ln.get("Price"), 0.0)
            discount_pct   = _flt(ln.get("DiscountPercent"), 0.0)
            uom_name       = (ln.get("UnitIDText") or "Cái").strip()

            product = odoo_utils._get_or_create_product(
                code=product_code,
                name=description,
                unit_name=uom_name,
                cost=price_unit,
                product_type="consu",
                purchase_ok=False,
                sale_ok=False,
            )

            seen_codes.add(product_code)
            if product_code in lines_by_code:
                lines_by_code[product_code].write({
                    'name': description,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'price_unit': price_unit,
                    'discount': discount_pct,
                })
            else:
                SaleLine.create({
                    'order_id': self.id,
                    'product_id': product.id,
                    'name': description,
                    'product_uom_qty': qty,
                    'price_unit': price_unit,
                    'discount': discount_pct,
                })

        # (tuỳ) xoá line không còn trong MISA
        for code, l in lines_by_code.items():
            if code not in seen_codes:
                l.unlink()

        # 5) Confirm nếu còn nháp
        if self.state in ('draft', 'sent'):
            self.action_confirm()

        # 6) Đảm bảo 1 picking + đặt tên theo MISA
        self._ensure_single_picking(desired_name=(delivery_no or order_no or self.name))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _("Đồng bộ thành công"), 'message': self.name, 'type': 'success'}
        }

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



    def action_resync_from_misa_hard(self):
        """Hủy & xóa SO rồi tạo lại từ MISA.
        Chỉ cho phép khi KHÔNG có picking 'done' và KHÔNG có invoice 'posted'."""
        self.ensure_one()
        odoo_utils = self.env['odoo.utils']

        # 1) Prefetch dữ liệu MISA trước khi đụng dữ liệu hiện hữu
        data = self._misa_fetch_order()
        misa_order_id = data.get("ID") or data.get("CustomID") or self.misa_id
        lines = self._misa_fetch_lines(misa_order_id)

        # 2) Kiểm tra điều kiện an toàn
        if any(p.state == 'done' for p in self.picking_ids):
            raise UserError(_("Không thể xoá & tạo lại vì có phiếu giao đã 'done'."))
        posted_invoices = self.invoice_ids.filtered(lambda m: m.state == 'posted')
        if posted_invoices:
            raise UserError(_("Không thể xoá & tạo lại vì đã có hoá đơn 'posted'."))

        # Lưu vài thông tin trước khi xóa
        old_name = self.name
        old_wh = self.warehouse_id

        # 3) HỦY SO trước (bắt buộc) -> sẽ hủy pickings/moves liên quan
        #    Nếu có move_line nào đang có qty_done>0 nhưng chưa validate, action_cancel vẫn xử lý,
        #    nhưng nếu module tùy biến cản trở, có thể reset qty_done trước (ít gặp).
        self.action_cancel()

        # 4) XÓA pickings (đã bị chuyển về 'cancel' sau action_cancel)
        for p in self.picking_ids:
            if p.state not in ('cancel', 'done'):
                # dự phòng: nếu vì lý do nào đó vẫn chưa cancel, thì cancel rồi unlink
                try:
                    if hasattr(p, 'action_cancel'):
                        p.action_cancel()
                except Exception as e:
                    _logger.warning("Huỷ picking %s lỗi: %s", p.name, e)
            try:
                if p.state != 'done':
                    p.unlink()
            except Exception as e:
                _logger.warning("Xoá picking %s lỗi: %s", p.name, e)

        # 5) XÓA invoices ở draft/cancel (nếu có)
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

        # 6) XÓA SO (đã ở trạng thái 'cancel')
        self.unlink()

        # 7) TẠO LẠI SO từ dữ liệu MISA đã hút
        partner_name = data.get("AccountIDText") or data.get("BillingAccountIDText") or _("Khách hàng MISA")
        partner = odoo_utils._get_or_create_partner(partner_name)
        order_no    = data.get("MISAOrderNo") or data.get("ListOrderNumber") or data.get("SaleOrderNo") or old_name
        delivery_no = data.get("DeliveryOrderNumber") or order_no
        book_date   = data.get("BookDate") or data.get("InvoiceDate") or data.get("DeliveryDate")
        shipping_addr = data.get("BillingAddress") or ''

        # tạo/gán địa chỉ giao (tái dùng helper bên wizard)
        try:
            delivery_contact = self.env['sale.api.import.wizard']._get_or_create_delivery_contact(
                parent_partner=partner,
                addr_str=shipping_addr,
                phone=data.get("Phone"),
                province_text=data.get("BillingProvinceIDText") or data.get("ShippingProvinceIDText"),
            )
            shipping_id = delivery_contact.id
        except Exception as e:
            _logger.warning("Không set delivery contact: %s", e)
            shipping_id = False

        vals_create = {
            'name': order_no,                     # giữ mã SO theo MISA nếu có
            'partner_id': partner.id,
            'origin': order_no,
            'warehouse_id': old_wh.id or False,
            'misa_id': str(misa_order_id) if misa_order_id else False,
            'partner_shipping_id': shipping_id,
        }
        if book_date:
            try:
                vals_create['date_order'] = dtparse(book_date).replace(tzinfo=None)
            except Exception:
                pass

        new_so = self.env['sale.order'].create(vals_create)

        def _flt(x, dv=0.0):
            try:
                return float(x or 0.0)
            except Exception:
                return dv

        for ln in (lines or []):
            product_code = ln.get("ProductIDText")
            description  = ln.get("Description") or product_code
            qty          = _flt(ln.get("Amount"), 0.0)
            price_unit   = _flt(ln.get("Price"), 0.0)
            discount_pct = _flt(ln.get("DiscountPercent"), 0.0)
            uom_name     = (ln.get("UnitIDText") or "Cái").strip()

            product = odoo_utils._get_or_create_product(
                code=product_code,
                name=description,
                unit_name=uom_name,
                cost=price_unit,
                product_type="consu",
                purchase_ok=False,
                sale_ok=False,
            )
            self.env['sale.order.line'].create({
                'order_id': new_so.id,
                'product_id': product.id,
                'name': description,
                'product_uom_qty': qty,
                'price_unit': price_unit,
                'discount': discount_pct,
            })

        # 8) Confirm & đặt tên picking theo MISA
        if new_so.state in ('draft', 'sent'):
            new_so.action_confirm()
        if new_so.picking_ids:
            picking = new_so.picking_ids[0]
            desired = delivery_no or order_no
            exists = self.env['stock.picking'].search([('name', '=', desired), ('id', '!=', picking.id)], limit=1)
            picking.name = f"{desired}-{picking.id}" if exists else desired

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _("Đồng bộ (xoá & tạo lại) thành công"), 'message': order_no, 'type': 'success'}
        }