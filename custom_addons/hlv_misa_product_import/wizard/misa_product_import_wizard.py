import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MisaProductImportWizard(models.TransientModel):
    _name = 'misa.product.import.wizard'
    _description = 'Import sản phẩm từ MISA CRM'

    product_code = fields.Char(string='Mã sản phẩm (default_code)', required=True)
    result_message = fields.Text(string='Kết quả', readonly=True)
    state = fields.Selection([
        ('draft', 'Nhập mã'),
        ('done', 'Hoàn tất'),
    ], default='draft')

    # Các trường hiển thị kết quả tìm kiếm từ CRM (cho user xác nhận)
    crm_product_name = fields.Char(string='Tên SP (CRM)', readonly=True)
    crm_product_code = fields.Char(string='Mã SP (CRM)', readonly=True)
    crm_product_price = fields.Float(string='Giá bán (CRM)', readonly=True)
    crm_product_unit = fields.Char(string='Đơn vị (CRM)', readonly=True)
    crm_product_category = fields.Char(string='Nhóm SP (CRM)', readonly=True)
    crm_product_tax = fields.Char(string='Thuế (CRM)', readonly=True)
    crm_misa_id = fields.Char(string='MISA ID', readonly=True)

    def action_search_and_import(self):
        """Tìm kiếm sản phẩm trên MISA CRM theo code và tạo trong Odoo"""
        self.ensure_one()
        code = self.product_code.strip()

        if not code:
            raise UserError(_("Vui lòng nhập mã sản phẩm."))

        # 1. Kiểm tra sản phẩm đã tồn tại trong Odoo chưa
        existing = self.env['product.template'].sudo().search(
            [('default_code', '=', code)], limit=1
        )
        if existing:
            self.write({
                'state': 'done',
                'result_message': f"⚠️ Sản phẩm với mã '{code}' đã tồn tại trong Odoo!\n"
                                  f"Tên: {existing.name}\n"
                                  f"ID: {existing.id}",
            })
            return self._reopen_wizard()

        # 2. Tìm kiếm trên MISA CRM
        try:
            misa_api = self.env['misa.api.utils'].sudo()
            results = misa_api.search_product_by_name(code=code, limit=5)
        except Exception as e:
            raise UserError(_("Lỗi khi tìm kiếm trên MISA CRM: %s") % str(e))

        if not results:
            self.write({
                'state': 'done',
                'result_message': f"❌ Không tìm thấy sản phẩm với mã '{code}' trên MISA CRM.",
            })
            return self._reopen_wizard()

        # Tìm sản phẩm khớp chính xác mã
        matched = None
        for p in results:
            if p.get('code') and p['code'].strip().upper() == code.upper():
                matched = p
                break

        if not matched:
            # Nếu không khớp chính xác, lấy kết quả đầu tiên
            matched = results[0]
            _logger.info("Không tìm thấy khớp chính xác mã '%s', dùng kết quả đầu: %s", code, matched.get('code'))

        # 3. Tạo sản phẩm trong Odoo
        try:
            product = self._create_odoo_product(matched, code)
        except Exception as e:
            raise UserError(_("Lỗi khi tạo sản phẩm Odoo: %s") % str(e))

        self.write({
            'state': 'done',
            'crm_product_name': matched.get('name'),
            'crm_product_code': matched.get('code'),
            'crm_product_price': matched.get('price', 0),
            'crm_product_unit': matched.get('unit'),
            'crm_product_category': matched.get('category'),
            'crm_product_tax': matched.get('tax'),
            'crm_misa_id': str(matched.get('misa_id', '')),
            'result_message': f"✅ Đã tạo sản phẩm thành công!\n"
                              f"Tên: {product.name}\n"
                              f"Mã: {product.default_code}\n"
                              f"ID Odoo: {product.id}",
        })
        return self._reopen_wizard()

    def _create_odoo_product(self, misa_data, original_code):
        """Tạo sản phẩm trong Odoo từ dữ liệu MISA CRM"""
        name = misa_data.get('name', original_code)
        price = misa_data.get('price', 0) or 0
        unit_name = misa_data.get('unit')
        tax_text = misa_data.get('tax', '')

        vals = {
            'name': name,
            'default_code': original_code,
            'list_price': float(price),
            'type': 'consu',
            'is_storable': True,
            'available_in_pos': True,
        }

        # Tìm UoM
        if unit_name:
            uom = self.env['uom.uom'].sudo().search([('name', '=', unit_name)], limit=1)
            if uom:
                vals['uom_id'] = uom.id
                vals['uom_po_id'] = uom.id

        # Tìm/tạo thuế
        if tax_text:
            tax_rate = self._parse_tax_rate(tax_text)
            if tax_rate is not None:
                try:
                    tax = self.env['odoo.utils'].sudo()._get_or_create_vn_vat(tax_rate, use='sale')
                    if tax:
                        vals['taxes_id'] = [(6, 0, [tax.id])]
                except Exception:
                    _logger.warning("Không thể tạo thuế cho rate: %s", tax_rate)

        # Tìm POS category từ MISA category
        category_name = misa_data.get('category')
        if category_name:
            pos_categ = self.env['pos.category'].sudo().search(
                [('name', 'ilike', category_name)], limit=1
            )
            if pos_categ:
                vals['pos_categ_ids'] = [(6, 0, [pos_categ.id])]

        product = self.env['product.template'].sudo().create(vals)
        _logger.info("✅ Đã tạo sản phẩm Odoo từ MISA CRM: %s [%s] (ID: %s)", name, original_code, product.id)
        return product

    @staticmethod
    def _parse_tax_rate(tax_text):
        """Trích xuất % thuế từ chuỗi text, ví dụ: 'Thuế GTGT 10%' -> 10.0"""
        import re
        if not tax_text:
            return None
        match = re.search(r'(\d+(?:\.\d+)?)\s*%', str(tax_text))
        if match:
            return float(match.group(1))
        return None

    def _reopen_wizard(self):
        """Trả về action để mở lại wizard với dữ liệu cập nhật"""
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
