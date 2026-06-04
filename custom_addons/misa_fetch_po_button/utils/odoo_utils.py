from odoo import models
import logging
import requests

_logger = logging.getLogger(__name__)

class OdooUtils(models.AbstractModel):
    _name = 'odoo.utils'
    _description = 'Odoo Utilities'

    def _get_or_create_partner(self, name, misa_code=None, tax_code=None):
        """Tìm hoặc tạo mới đối tác (partner) dựa trên tên.

        Thứ tự tìm kiếm:
          1. Tìm root company (parent_id=False) theo misa_code (ref hoặc company_registry).
          2. Tìm root company theo tên chính xác.
          3. Nếu không tìm được → tạo mới root company.

        Không bao giờ tạo partner con (parent_id set) để tránh gây duplicate
        là_company=True dưới một công ty khác.
        """
        name = (name or "").strip()
        misa_code = (misa_code or "").strip()
        tax_code = (tax_code or "").strip()
        Partner = self.env["res.partner"]

        # MISA CRM can have multiple accounts with the same company name but
        # different customer codes. When misa_code is provided, use it as the
        # primary key and never fall back to name matching.
        if misa_code:
            candidates = Partner.search([
                ("parent_id", "=", False),
                ("is_company", "=", True),
                "|",
                ("ref", "=", misa_code),
                ("company_registry", "=", misa_code),
            ], order="id asc")
            partner = candidates.filtered(
                lambda p: (p.ref or "").strip() == misa_code
                or (not p.ref and (p.company_registry or "").strip() == misa_code)
            )
            if tax_code:
                tax_match = partner.filtered(lambda p: (p.vat or "").strip() == tax_code)[:1]
                if tax_match:
                    _logger.info("Use existing partner by MISA key %s-%s: %s", tax_code, misa_code, tax_match.name)
                    return tax_match

                no_tax = partner.filtered(lambda p: not (p.vat or "").strip())[:1]
                if no_tax:
                    vals = {"vat": tax_code}
                    if not no_tax.ref:
                        vals["ref"] = misa_code
                    if not no_tax.company_registry:
                        vals["company_registry"] = misa_code
                    no_tax.write(vals)
                    _logger.info("Use existing partner by code %s and fill VAT=%s: %s", misa_code, tax_code, no_tax.name)
                    return no_tax

                if partner:
                    _logger.warning(
                        "MISA key mismatch for code %s tax %s. Existing partner ids=%s; creating a new root company.",
                        misa_code,
                        tax_code,
                        partner.ids,
                    )

            partner = partner[:1]
            if partner:
                _logger.info("Use existing partner by MISA code %s: %s", misa_code, partner.name)
                return partner

            vals = {
                "name": name,
                "customer_rank": 1,
                "is_company": True,
                "ref": misa_code,
                "company_registry": misa_code,
            }
            if tax_code:
                vals["vat"] = tax_code
            partner = Partner.create(vals)
            _logger.info("Created partner by MISA key %s-%s: %s", tax_code or "-", misa_code, name)
            return partner

        partner = Partner.search([
            ("name", "=", name),
            ("parent_id", "=", False),
            ("is_company", "=", True),
        ], limit=1)

        if not partner:
            # Fallback: tìm partner bất kỳ (kể cả không is_company) cùng tên + root
            partner = Partner.search([
                ("name", "=", name),
                ("parent_id", "=", False),
            ], limit=1)

        if partner:
            _logger.info("Use existing partner by name without MISA code: %s", partner.name)
            return partner

        vals = {"name": name, "customer_rank": 1, "is_company": True}
        partner = Partner.create(vals)
        _logger.info("Created partner without MISA code: %s", name)
        return partner

    def _get_or_create_uom(self, name):
        """Tìm hoặc tạo mới đơn vị tính (UoM) dựa trên tên."""
        name = name.strip().title()
        UoM = self.env['uom.uom']
        UoMCat = self.env['uom.category']

        uom = UoM.search([('name', '=', name)], limit=1)
        if uom:
            return uom

        cat = UoMCat.search([('name', 'ilike', 'Unit')], limit=1)
        if not cat:
            cat = UoMCat.create({'name': 'Unit'})

        ref_uom = UoM.search([
            ('category_id', '=', cat.id),
            ('uom_type', '=', 'reference')
        ], limit=1)

        uom_type = 'reference' if not ref_uom else 'smaller'
        factor = 1.0

        return UoM.create({
            'name': name,
            'category_id': cat.id,
            'uom_type': uom_type,
            'factor_inv': factor,
            'rounding': 1.0,
        })

    def _get_or_create_product(self, code, name, unit_name, cost=0.0, product_type="consu", purchase_ok=True, sale_ok=False):
        """
        Tìm hoặc tạo mới sản phẩm dựa trên mã.
        Nếu tìm thấy → CẬP NHẬT: tên (từ MISA).
        """
        code = code.strip()
        name = name.strip()
        product = self.env["product.product"].search([("default_code", "=", code)], limit=1)
        
        if product:
            # ✅ CẬP NHẬT tên từ MISA nếu khác
            tmpl = product.product_tmpl_id
            if tmpl.name != name:
                tmpl.write({'name': name})
                _logger.info("📝 Cập nhật tên sản phẩm %s: '%s' → '%s'", code, tmpl.name, name)
            else:
                _logger.info("🔁 Sản phẩm %s đã tồn tại và không thay đổi", code)
            
            return product

        # Tạo mới nếu chưa có
        uom = self._get_or_create_uom(unit_name)
        tmpl = self.env["product.template"].create({
            "name": name,
            "default_code": code,
            "type": product_type,
            "uom_id": uom.id,
            "uom_po_id": uom.id,
            "standard_price": cost,
            "purchase_ok": purchase_ok,
            "sale_ok": sale_ok,
            "is_storable": True
        })
        _logger.info("🆕 Tạo sản phẩm %s với UOM: %s", code, uom.name)
        return tmpl.product_variant_id
    
    
    def _sync_product_name_from_misa(self, product_code, product_name):
        """
        Đồng bộ tên sản phẩm từ MISA.
        Tìm sản phẩm theo code và cập nhật tên nếu khác.
        """
        if not product_code or not product_name:
            return None
            
        code = product_code.strip()
        name = product_name.strip()
        
        product = self.env["product.product"].search([("default_code", "=", code)], limit=1)
        if product:
            tmpl = product.product_tmpl_id
            if tmpl.name != name:
                tmpl.write({'name': name})
                _logger.info("📝 Cập nhật tên sản phẩm %s: '%s' → '%s'", code, tmpl.name, name)
        return product
    
    def _update_picking_lines(self, picking, lines):
        """
        Cập nhật các dòng move của stock.picking theo danh sách lines mới từ MISA.
        - Tạo mới nếu chưa có.
        - Cập nhật số lượng nếu khác.
        - Xóa nếu không còn tồn tại trong lines.
        """
        existing_moves = {
            (m.product_id.default_code or '', m.product_id.id): m
            for m in picking.move_ids_without_package
        }
        misa_lines = {}
        for line in lines:
            product_code = str(line.get("inventory_item_code", "")).strip()
            product_name = str(line.get("description", "")).strip()
            uom_name = str(line.get("unit_name", "Cái")).strip()
            qty = float(line.get("quantity", 0))
            cost = float(line.get("unit_price_finance", 0) or 0)

            if not product_code or not product_name or qty <= 0:
                _logger.warning("⚠️ Bỏ qua dòng không hợp lệ: %s", line)
                continue

            product = self._get_or_create_product(
                code=product_code,
                name=product_name,
                unit_name=uom_name,
                cost=cost,
                product_type="consu",
                purchase_ok=False,
                sale_ok=False,

            )
            key = (product_code, product.id)
            if key in misa_lines:
                misa_lines[key]['qty'] += qty  # cộng dồn số lượng
            else:
                misa_lines[key] = {
                    'product': product,
                    'qty': qty,
                    'name': product_name
                }


        # Cập nhật hoặc thêm mới
        for key, line_data in misa_lines.items():
            product = line_data['product']
            qty = line_data['qty']
            name = line_data['name']

            if key in existing_moves:
                move = existing_moves[key]
                if float(move.product_uom_qty) != float(qty):
                    _logger.info("🔄 Cập nhật dòng %s: %s -> %s", product.default_code, move.product_uom_qty, qty)
                    move.write({'product_uom_qty': qty})
                existing_moves.pop(key)  # Đã xử lý rồi
            else:
                self.env['stock.move'].create({
                    'name': name,
                    'product_id': product.id,
                    'product_uom_qty': qty,
                    'product_uom': product.uom_id.id,
                    'picking_id': picking.id,
                    'location_id': picking.location_id.id,
                    'location_dest_id': picking.location_dest_id.id,
                })
                _logger.info("➕ Thêm dòng mới: %s x%s", product.default_code, qty)

        # Xóa những dòng không còn
        for move in existing_moves.values():
            _logger.info("❌ Xóa dòng thừa: %s x%s", move.product_id.default_code, move.product_uom_qty)
            move.unlink()
            
            
    def get_misa_product(self, token, code):
        code = code.strip()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Clientid": "odoo"
        }
        params = {
            "code": code
        }
        product_url = "https://crmconnect.misa.vn/api/v2/Products/code"

        try:
            response = requests.get(product_url, headers=headers, params=params)
            _logger.warning("🔄 API response: %s", response.text)

            if response.status_code != 200:
                raise Exception(f"❌ MISA trả về mã lỗi: {response.status_code}")

            res_json = response.json()

            if not res_json.get("success"):
                raise Exception(f"❌ MISA báo lỗi: {res_json.get('error_message')}")

            data = res_json.get("data")  or []
            # không tim thấy thì tạo mã tạm

            if not data or not isinstance(data, list):
                _logger.warning("⚠️ MISA không trả về dữ liệu sản phẩm cho mã: %s. Tạo tạm với mã thôi.", code)
                name = code
                cost = 0.0
                unit_name = "Cái"
            else:
                product_data = data[0]
                name = product_data.get("product_name") or code
                cost = product_data.get("unit_cost") or 0.0
                unit_name = product_data.get("usage_unit") or "Cái"

            purchase_ok = True
            sale_ok = True

            uom = self._get_or_create_uom(unit_name)
            tmpl = self.env["product.template"].create({
                "name": name,
                "default_code": code,
                "type": "consu",  # hoặc `product_type` nếu có biến này ở đâu đó
                "uom_id": uom.id,
                "uom_po_id": uom.id,
                "standard_price": cost,
                "purchase_ok": purchase_ok,
                "sale_ok": sale_ok,
                "is_storable": True,
            })
            _logger.info("🆕 Tạo sản phẩm %s với UOM từ MISA: %s", code, uom.name)
            return tmpl.product_variant_id

        except Exception as e:
            _logger.error("💥 Lỗi khi lấy sản phẩm từ MISA: %s", str(e))
            raise

    
    
    
    def _get_token_api_crm():
        token_url = "https://crmconnect.misa.vn/api/v2/Account"
        payload = {
            "client_id": "odoo",
            "client_secret": "iqFXzEnjLIpuSTdkwFhuvj1Y4jsD9zXHrUzZvF81bO8="
        }
        headers = {"Content-Type": "application/json"}

        try:
            res = requests.post(token_url, json=payload, headers=headers)
            _logger.info("🔐 Token response: %s", res.text)
            res.raise_for_status()
            token = res.json().get("data")
            if not token:
                raise Exception("❌ MISA không trả về access_token")
            return token
        except Exception as e:
            raise Exception(f"Lỗi lấy token từ MISA: {e}")
        
        
    
