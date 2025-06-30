from odoo import models
import logging
import requests

_logger = logging.getLogger(__name__)

class OdooUtils(models.AbstractModel):
    _name = 'odoo.utils'
    _description = 'Odoo Utilities'

    def _get_or_create_partner(self, name):
        """Tìm hoặc tạo mới đối tác (partner) dựa trên tên."""
        name = name.strip()
        partner = self.env["res.partner"].search([("name", "=", name)], limit=1)
        if not partner:
            partner = self.env["res.partner"].create({"name": name, "supplier_rank": 1})
            _logger.info("Tạo liên hệ mới: %s", name)
        else:
            _logger.info("Dùng liên hệ có sẵn: %s", name)
        return partner

    def _get_or_create_uom(self, name):
        """Tìm hoặc tạo mới đơn vị tính (UoM) dựa trên tên."""
        name = name.strip().title()
        UoM = self.env['uom.uom']
        UoMCat = self.env['uom.category']

        uom = UoM.search([('name', '=', name)], limit=1)
        if uom:
            return uom

        cat = UoMCat.search([('name', 'ilike', 'đơn vị')], limit=1)
        if not cat:
            cat = UoMCat.create({'name': 'Đơn vị'})

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
        """Tìm hoặc tạo mới sản phẩm dựa trên mã, tên, đơn vị tính và giá vốn."""
        code = code.strip()
        name = name.strip()
        product = self.env["product.product"].search([("default_code", "=", code)], limit=1)
        if product:
            _logger.info("🔁 Tìm thấy sản phẩm %s. Dùng UOM gốc: %s", code, product.uom_id.name)
            return product

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
            "is_storable": True,
        })
        _logger.info("🆕 Tạo sản phẩm %s với UOM: %s", code, uom.name)
        return tmpl.product_variant_id
    
    
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
                is_storable=True

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

            data = res_json.get("data")
            if not data or not isinstance(data, list):
                raise Exception("❌ Không tìm thấy thông tin sản phẩm.")

            product_data = data[0]

            name = product_data.get("product_name") or code
            cost = product_data.get("unit_cost") or 0.0
            purchase_ok = True
            sale_ok = True
            unit_name = product_data.get("usage_unit") or "Cái"

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