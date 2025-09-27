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
            note_text      = (ln.get("DescriptionProduct")
                  or ln.get("Note")
                  or "")

            product = odoo_utils._get_or_create_product(
                code=product_code,
                name=description,
                unit_name=uom_name,
                cost=price_unit,
                product_type="consu",
                purchase_ok=True,
                sale_ok=True,
            )

            seen_codes.add(product_code)
            if product_code in lines_by_code:
                lines_by_code[product_code].write({
                    'name': description,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'price_unit': price_unit,
                    'discount': discount_pct,
                    'note': note_text,
                })
            else:
                SaleLine.create({
                    'order_id': self.id,
                    'product_id': product.id,
                    'name': description,
                    'product_uom_qty': qty,
                    'price_unit': price_unit,
                    'discount': discount_pct,
                    'note': note_text,
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
        self.ensure_one()
        env = self.env
        odoo_utils = env['odoo.utils']

        # Lấy headers cho các call phụ (convert UoM)
        headers, _ = self._misa_headers()

        # 1) Lấy dữ liệu MISA trước khi đụng dữ liệu hiện hữu
        data = self._misa_fetch_order()
        misa_order_id = data.get("ID") or data.get("CustomID") or self.misa_id
        lines = self._misa_fetch_lines(misa_order_id)

        # 2) Chặn các trường hợp không an toàn
        if any(p.state == 'done' for p in self.picking_ids):
            # raise UserError(_("Không thể xoá & tạo lại vì có phiếu giao đã 'done'."))
            return self._partial_resync_open_pickings_when_done_present(data, lines, headers)
        if self.invoice_ids.filtered(lambda m: m.state == 'posted'):
            raise UserError(_("Không thể xoá & tạo lại vì đã có hoá đơn 'posted'."))

        # Lưu info trước khi xoá
        old_wh = self.warehouse_id
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
        self.sudo().unlink()

        # ===== 8) TẠO LẠI TỪ MISA =====
        partner_name  = data.get("AccountIDText") or data.get("BillingAccountIDText") or _("Khách hàng MISA")
        partner       = odoo_utils._get_or_create_partner(partner_name)
        order_no      = data.get("MISAOrderNo") or data.get("ListOrderNumber") or data.get("SaleOrderNo") or order_no_fallback
        delivery_no   = data.get("DeliveryOrderNumber") or order_no
        book_date     = data.get("BookDate") or data.get("InvoiceDate") or data.get("DeliveryDate")
        shipping_addr = data.get("BillingAddress") or ''
        origin        = data.get("SaleOrderName") or ''

        # địa chỉ giao hàng
        try:
            delivery_contact = env['sale.api.import.wizard']._get_or_create_delivery_contact(
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
            'name': order_no,
            'partner_id': partner.id,
            'origin': origin,
            'warehouse_id': old_wh.id or False,
            'misa_id': str(misa_order_id) if misa_order_id else False,
            'partner_shipping_id': shipping_id,
        }
        if book_date:
            from dateutil.parser import parse as dtparse
            try:
                vals_create['date_order'] = dtparse(book_date).replace(tzinfo=None)
            except Exception:
                pass

        new_so = env['sale.order'].create(vals_create)

        def _flt(x, dv=0.0):
            try:
                return float(x or 0.0)
            except Exception:
                return dv

        # ===== 8.1) THÊM LINES (có quy đổi UoM nếu khác mặc định) =====
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
            }
            # Nếu có convert, ép UoM line về UoM mặc định của product
            if not use_default_uom and product.uom_id:
                vals_line['product_uom'] = product.uom_id.id

            env['sale.order.line'].create(vals_line)

        # ===== 9) Confirm & đặt tên picking theo MISA =====
        if new_so.state in ('draft', 'sent'):
            new_so.action_confirm()
        if new_so.picking_ids:
            picking = new_so.picking_ids[0]
            desired = delivery_no or order_no
            exists = env['stock.picking'].search([('name', '=', desired), ('id', '!=', picking.id)], limit=1)
            picking.name = f"{desired}-{picking.id}" if exists else desired

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

        # Map các dòng SO hiện tại theo default_code để cập nhật/gộp về 1 dòng/mã
        so_lines_by_code = {}
        for line in self.order_line:
            code = (line.product_id and line.product_id.default_code) or ''
            if code:
                so_lines_by_code[code] = line

        seen_codes = set()

        for ln in (lines or []):
            code = (ln.get("ProductIDText") or "").strip()
            if not code:
                continue

            desc       = ln.get("Description") or code
            qty        = _flt(ln.get("Amount"), 0.0)
            price      = _flt(ln.get("Price"), 0.0)
            discount   = _flt(ln.get("DiscountPercent"), 0.0)
            uom_name   = (ln.get("UnitIDText") or "Cái").strip()
            misa_pid   = ln.get("ProductID") or ln.get("ProductId")
            note_text  = (ln.get("DescriptionProduct")
              or ln.get("Note")
              or "")

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

            vals_line = {
                'name': desc,
                'product_id': product.id,
                'product_uom_qty': qty_base,
                'price_unit': price_base,
                'discount': discount,
                'note': note_text,
            }
            if not is_default and product.uom_id:
                vals_line['product_uom'] = product.uom_id.id

            if code in so_lines_by_code:
                so_lines_by_code[code].write(vals_line)
            else:
                SaleLine.create(dict(vals_line, order_id=self.id))

            seen_codes.add(code)

        # (tuỳ chọn) Xoá dòng không còn trong MISA
        for code, line in so_lines_by_code.items():
            if code not in seen_codes:
                line.unlink()


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

        # --------- Bước 0: đưa dòng SO về đúng MISA (nếu không có invoice posted) ---------
        if self.invoice_ids.filtered(lambda inv: inv.state == 'posted'):
            _logger.warning("Bỏ qua cập nhật SO lines vì có hoá đơn 'posted'. Sẽ chỉ vá picking mở.")
        else:
            try:
                self._sync_so_lines_from_misa_no_picking(lines, headers)
            except Exception as exc:
                _logger.warning("Không thể đồng bộ SO lines: %s (tiếp tục vá picking)", exc)

        # --------- Bước 1: tổng đã giao theo picking DONE ----------
        delivered_by_product = {}
        done_picks = self.picking_ids.filtered(lambda p: p.state == 'done')
        _logger.info("Có %s picking đã DONE", len(done_picks))

        for picking in done_picks:
            _logger.debug("  DONE picking: %s", picking.name)
            for ml in picking.move_line_ids:
                prod = ml.product_id
                if not prod:
                    continue
                qty_delivered = float(getattr(ml, 'qty_done', 0.0) or 0.0)
                delivered_by_product[prod] = delivered_by_product.get(prod, 0.0) + qty_delivered
                _logger.debug("    Delivered %s: +%s (tổng=%s)",
                            prod.display_name, qty_delivered, delivered_by_product[prod])

        # --------- Bước 2: tổng theo MISA (quy về UoM mặc định) ----------
        def _flt(x, dv=0.0):
            try:
                return float(x or 0.0)
            except Exception:
                return dv

        misa_total_by_product = {}
        for ln in (lines or []):
            product_code = ln.get("ProductIDText")
            if not product_code:
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
        # --------- Bước 4: lấy/chuẩn bị picking mở ----------
        open_picks = self.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
        target_pick = open_picks[:1] and open_picks[0] or False
        _logger.info("Có %s picking đang mở; target_pick=%s",
                    len(open_picks), target_pick and target_pick.name)

        nothing_to_ship = all(qty <= 0.0 for qty in needed_in_open_by_product.values())

        if not target_pick and nothing_to_ship:
            _logger.info("Không còn gì cần trong picking mở và không có picking mở")
            self.message_post(body=_("Đồng bộ hoàn tất: Không cần picking mở thêm."))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {'title': _("Đồng bộ thành công"), 'message': _("Không cần picking mở thêm"), 'type': 'success'},
            }

        if not target_pick and not nothing_to_ship:
            _logger.info("Chưa có picking mở nhưng vẫn còn hàng cần giao → tạo mới")
            if self.state in ('draft', 'sent'):
                self.action_confirm()
            # refresh lại open_picks sau confirm
            open_picks = self.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
            target_pick = open_picks[:1] and open_picks[0] or False
            if not target_pick:
                picking_type = self.warehouse_id and self.warehouse_id.out_type_id
                if not picking_type:
                    raise UserError(_("Không xác định được loại phiếu giao (picking type) của kho %s")
                                    % (self.warehouse_id.name or ''))
                target_pick = env['stock.picking'].create({
                    'partner_id': self.partner_id.id,
                    'picking_type_id': picking_type.id,
                    'origin': self.name,
                    'location_id': picking_type.default_location_src_id.id,
                    'location_dest_id': picking_type.default_location_dest_id.id,
                    'sale_id': self.id,
                })
                _logger.info("Đã tạo picking mới: %s", target_pick.name)
            # đồng bộ biến open_picks cho các bước sau
            open_picks = self.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))

        # --------- Bước 5: lập chỉ mục move mở (theo product_id và fallback theo default_code) ----------
        open_moves_by_product = {}
        open_moves_by_code = {}

        for picking in (open_picks or [target_pick]):
            if not picking:
                continue
            for mv in picking.move_ids_without_package.filtered(lambda m: m.state not in ('done', 'cancel')):
                # theo product (record)
                open_moves_by_product.setdefault(mv.product_id, []).append(mv)
                # fallback theo mã
                code = (mv.product_id.default_code or '').strip()
                if code:
                    open_moves_by_code.setdefault(code, []).append(mv)
                _logger.debug("Open move %s: %s qty=%s state=%s",
                            picking.name, mv.product_id.display_name, mv.product_uom_qty, mv.state)

        # --------- Bước 6: cập nhật/cắt/tạo move theo needed_in_open ----------
        StockMove = env['stock.move']

        # 6.1: với các sản phẩm needed=0 → cancel/qty=0 tất cả move mở
        for prod, mv_list in open_moves_by_product.items():
            if needed_in_open_by_product.get(prod, 0.0) <= 0.0:
                _logger.info("Huỷ/cắt các move của %s (needed=0)", prod.display_name)
                for mv in mv_list:
                    self._safe_cancel_move(mv)

        # 6.2: các sản phẩm needed > 0 → cập nhật hoặc tạo move
        for prod, needed_qty in needed_in_open_by_product.items():
            if needed_qty <= 0.0:
                continue

            # Lấy các move mở hiện có theo product; nếu không thấy, fallback theo mã
            existing_moves = open_moves_by_product.get(prod, [])
            if not existing_moves:
                code = (prod.default_code or '').strip()
                if code:
                    existing_moves = open_moves_by_code.get(code, []) or []

            # Lọc chỉ move thật sự còn mở
            existing_moves = [mv for mv in existing_moves if mv.state not in ('done', 'cancel')]

            if existing_moves:
                main_mv = existing_moves[0]
                self._safe_unreserve_move(main_mv)
                # cập nhật số lượng & UoM (về UoM mặc định của product)
                main_mv.write({
                    'product_uom_qty': needed_qty,
                    'product_uom': prod.uom_id.id if prod.uom_id else main_mv.product_uom.id,
                })
                _logger.info("Cập nhật move %s → qty=%s", main_mv.display_name, needed_qty)

                # cancel các move dư
                for extra_mv in existing_moves[1:]:
                    _logger.info("Cancel move thừa %s", extra_mv.display_name)
                    self._safe_cancel_move(extra_mv)
            else:
                # Tạo move mới
                _logger.info("Tạo move mới cho %s với số lượng %s", prod.display_name, needed_qty)
                move_vals = {
                    'name': prod.display_name,
                    'product_id': prod.id,
                    'product_uom_qty': needed_qty,
                    'product_uom': prod.uom_id.id if prod.uom_id else env.ref('uom.product_uom_unit').id,
                    'picking_id': target_pick.id,
                    'location_id': target_pick.location_id.id,
                    'location_dest_id': target_pick.location_dest_id.id,
                    'state': 'draft',
                    'sale_line_id': False,  # có thể map theo SOL nếu cần
                }
                new_mv = StockMove.create(move_vals)
                try:
                    if hasattr(new_mv, '_action_confirm'):
                        new_mv._action_confirm()
                    else:
                        new_mv.action_confirm()
                except Exception as exc:
                    _logger.warning("Xác nhận move mới lỗi: %s", exc)

        # --------- Bước 7: re-assign (giữ chỗ) ----------
        if target_pick and any(qty > 0 for qty in needed_in_open_by_product.values()):
            try:
                if target_pick.state == 'draft' and hasattr(target_pick, 'action_confirm'):
                    target_pick.action_confirm()
                if hasattr(target_pick, 'action_assign'):
                    target_pick.action_assign()
                _logger.info("Đã re-assign picking %s", target_pick.name)
            except Exception as exc:
                _logger.warning("Không thể reserve lại picking %s: %s", target_pick.name, exc)

        # --------- Bước 8: thông báo kết quả ----------
        summary_parts = []
        for prod, needed in needed_in_open_by_product.items():
            if needed > 0:
                summary_parts.append(f"{prod.display_name}: {needed:g}")

        summary = _("Picking mở cần: %s") % (", ".join(summary_parts) if summary_parts else _("không có gì"))
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

