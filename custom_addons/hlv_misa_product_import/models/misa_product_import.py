import logging
import re
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MisaProductImport(models.Model):
    _name = 'misa.product.import'
    _description = 'Import sản phẩm từ MISA CRM'
    _order = 'create_date desc'

    name = fields.Char(string='Mã sản phẩm', required=True)
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('found', 'Tìm thấy'),
        ('done', 'Đã tạo'),
        ('exists', 'Đã tồn tại'),
        ('not_found', 'Không tìm thấy'),
        ('error', 'Lỗi'),
    ], default='draft', string='Trạng thái', readonly=True)
    result_message = fields.Text(string='Kết quả', readonly=True)

    # Thông tin từ CRM
    crm_product_name = fields.Char(string='Tên SP (CRM)', readonly=True)
    crm_product_code = fields.Char(string='Mã SP (CRM)', readonly=True)
    crm_product_price = fields.Float(string='Giá bán (CRM)', readonly=True)
    crm_product_unit = fields.Char(string='Đơn vị (CRM)', readonly=True)
    crm_product_category = fields.Char(string='Nhóm SP (CRM)', readonly=True)
    crm_product_tax = fields.Char(string='Thuế (CRM)', readonly=True)
    crm_misa_id = fields.Char(string='MISA ID', readonly=True)

    # Link tới sản phẩm đã tạo
    product_id = fields.Many2one('product.template', string='Sản phẩm Odoo', readonly=True)

    def action_search_crm(self):
        """Bước 1: Kiểm tra Odoo + tìm kiếm trên MISA CRM"""
        self.ensure_one()
        code = self.name.strip()

        if not code:
            raise UserError(_("Vui lòng nhập mã sản phẩm."))

        # 1. Kiểm tra sản phẩm đã tồn tại trong Odoo chưa
        existing = self.env['product.template'].sudo().search(
            [('default_code', '=', code)], limit=1
        )
        if existing:
            self.write({
                'state': 'exists',
                'product_id': existing.id,
                'result_message': f"Sản phẩm với mã '{code}' đã tồn tại trong Odoo.\n"
                                  f"Tên: {existing.name} | ID: {existing.id}",
            })
            return True

        # 2. Tìm kiếm trên MISA CRM bằng code
        try:
            misa_api = self.env['misa.api.utils'].sudo()
            results = misa_api.search_product_by_name(name=None, code=code, limit=10)
        except Exception as e:
            self.write({
                'state': 'error',
                'result_message': f"Lỗi khi tìm kiếm trên MISA CRM: {e}",
            })
            return True

        if not results:
            self.write({
                'state': 'not_found',
                'result_message': f"Không tìm thấy sản phẩm với mã '{code}' trên MISA CRM.",
            })
            return True

        # Tìm sản phẩm khớp chính xác mã
        matched = None
        for p in results:
            if p.get('code') and p['code'].strip().upper() == code.upper():
                matched = p
                break

        if not matched:
            matched = results[0]
            _logger.info("Không khớp chính xác mã '%s', dùng kết quả đầu: %s", code, matched.get('code'))

        self.write({
            'state': 'found',
            'crm_product_name': matched.get('name'),
            'crm_product_code': matched.get('code'),
            'crm_product_price': matched.get('price', 0) or 0,
            'crm_product_unit': matched.get('unit'),
            'crm_product_category': matched.get('category'),
            'crm_product_tax': matched.get('tax'),
            'crm_misa_id': str(matched.get('misa_id', '')),
            'result_message': f"Tìm thấy sản phẩm '{matched.get('name')}' trên MISA CRM. Bấm 'Tạo sản phẩm' để import vào Odoo.",
        })
        return True

    def action_create_product(self):
        """Bước 2: Tạo sản phẩm trong Odoo từ dữ liệu CRM đã tìm thấy"""
        self.ensure_one()
        if self.state != 'found':
            raise UserError(_("Cần tìm kiếm trước khi tạo sản phẩm."))

        code = self.name.strip()

        # Double-check chưa tồn tại
        existing = self.env['product.template'].sudo().search(
            [('default_code', '=', code)], limit=1
        )
        if existing:
            self.write({
                'state': 'exists',
                'product_id': existing.id,
                'result_message': f"Sản phẩm với mã '{code}' đã được tạo trước đó.",
            })
            return True

        try:
            product = self._create_odoo_product()
            self.write({
                'state': 'done',
                'product_id': product.id,
                'result_message': f"Đã tạo sản phẩm thành công: {product.name} [{product.default_code}]",
            })
        except Exception as e:
            raise UserError(_("Lỗi khi tạo sản phẩm Odoo: %s") % str(e))

        return True

    def action_open_product(self):
        """Mở sản phẩm đã tạo/tìm thấy"""
        self.ensure_one()
        if not self.product_id:
            raise UserError(_("Chưa có sản phẩm liên kết."))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'product.template',
            'res_id': self.product_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_reset(self):
        """Reset về trạng thái nháp để tìm lại"""
        self.ensure_one()
        self.write({
            'state': 'draft',
            'result_message': False,
            'crm_product_name': False,
            'crm_product_code': False,
            'crm_product_price': 0,
            'crm_product_unit': False,
            'crm_product_category': False,
            'crm_product_tax': False,
            'crm_misa_id': False,
            'product_id': False,
        })
        return True

    def _create_odoo_product(self):
        """Tạo sản phẩm trong Odoo từ dữ liệu CRM đã lưu"""
        code = self.name.strip()
        name = self.crm_product_name or code
        price = self.crm_product_price or 0

        vals = {
            'name': name,
            'default_code': code,
            'list_price': float(price),
            'type': 'consu',
            'is_storable': True,
            'available_in_pos': True,
        }

        # Tìm UoM
        if self.crm_product_unit:
            uom = self.env['uom.uom'].sudo().search(
                [('name', '=', self.crm_product_unit)], limit=1
            )
            if uom:
                vals['uom_id'] = uom.id
                vals['uom_po_id'] = uom.id

        # Tìm/tạo thuế
        if self.crm_product_tax:
            tax_rate = self._parse_tax_rate(self.crm_product_tax)
            if tax_rate is not None:
                try:
                    tax = self.env['odoo.utils'].sudo()._get_or_create_vn_vat(tax_rate, use='sale')
                    if tax:
                        vals['taxes_id'] = [(6, 0, [tax.id])]
                except Exception:
                    _logger.warning("Không thể tạo thuế cho rate: %s", tax_rate)

        # Tìm POS category
        if self.crm_product_category:
            pos_categ = self.env['pos.category'].sudo().search(
                [('name', 'ilike', self.crm_product_category)], limit=1
            )
            if pos_categ:
                vals['pos_categ_ids'] = [(6, 0, [pos_categ.id])]

        product = self.env['product.template'].sudo().create(vals)
        _logger.info("Đã tạo SP Odoo từ MISA CRM: %s [%s] (ID: %s)", name, code, product.id)
        return product

    @staticmethod
    def _parse_tax_rate(tax_text):
        if not tax_text:
            return None
        match = re.search(r'(\d+(?:\.\d+)?)\s*%', str(tax_text))
        if match:
            return float(match.group(1))
        return None
