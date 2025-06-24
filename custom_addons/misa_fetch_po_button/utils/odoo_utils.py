from odoo import models
import logging

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