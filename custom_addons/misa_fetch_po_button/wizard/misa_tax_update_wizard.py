# -*- coding: utf-8 -*-
"""
Wizard cập nhật thuế sản phẩm từ MISA
"""
from odoo import models, fields, api
import logging
import re
import base64

_logger = logging.getLogger(__name__)

class MisaTaxUpdateWizard(models.TransientModel):
    _name = 'misa.tax.update.wizard'
    _description = 'Cập nhật thuế sản phẩm từ MISA'

    log_text = fields.Text(string='Kết quả', readonly=True)
    state = fields.Selection([
        ('draft', 'Chuẩn bị'),
        ('done', 'Hoàn thành')
    ], default='draft')

    def action_update_tax(self):
        """Thực hiện cập nhật thuế"""
        self.ensure_one()
        
        logs = []
        logs.append("=" * 50)
        logs.append("CẬP NHẬT THUẾ SẢN PHẨM TỪ MISA")
        logs.append("=" * 50)
        
        try:
            from odoo.addons.misa_fetch_po_button.utils.misa_product_export import MisaProductExporter
            exporter = MisaProductExporter(self.env)
            
            # 1. LOAD TOÀN BỘ SẢN PHẨM ODOO VÀO BỘ NHỚ
            logs.append("\n⏳ Đang tải danh sách sản phẩm Odoo...")
            product_model = self.env['product.template'].sudo()
            # Tìm tất cả sản phẩm
            odoo_products = product_model.search_read(
                [('default_code', '!=', False)],
                ['default_code', 'taxes_id']
            )
            
            odoo_map = {}
            for p in odoo_products:
                code = p['default_code'].strip()
                odoo_map[code] = {
                    'id': p['id'],
                    'taxes_id': p['taxes_id']
                }
            logs.append(f"✅ Đã tải {len(odoo_map)} sản phẩm Odoo.")

            # 2. CACHE TAXES
            tax_map = {} # amount -> tax_id
            taxes = self.env['account.tax'].search([('type_tax_use', '=', 'sale')])
            for t in taxes:
                if t.amount not in tax_map:
                    tax_map[t.amount] = t.id
            logs.append(f"✅ Đã tải {len(taxes)} loại thuế bán ra.")

            # 3. FETCH MISA PRODUCTS (CHỈ LẤY CODE VÀ TAX)
            logs.append("\n⏳ Đang tải dữ liệu từ MISA...")
            # ProductCode, TaxID, TaxIDText
            # Base64: UHJvZHVjdENvZGUsVGF4SUQsVGF4SURUZXh0
            minimal_columns = "UHJvZHVjdENvZGUsVGF4SUQsVGF4SURUZXh0"
            misa_products = exporter.fetch_all_products(page_size=1000, columns=minimal_columns)
            logs.append(f"✅ Đã tải {len(misa_products)} sản phẩm từ MISA.")
            
            # 4. UPDATE
            logs.append("\n🔄 Đang xử lý cập nhật...")
            products_updated = 0
            products_not_found = 0
            
            for p in misa_products:
                code = (p.get("ProductCode") or "").strip()
                if not code:
                    continue
                
                if code not in odoo_map:
                    products_not_found += 1
                    continue
                    
                odoo_info = odoo_map[code]
                
                # Parse thuế
                tax_text = str(p.get("TaxIDText") or "")
                # Regex tìm số thực
                nums = re.findall(r"[-+]?\d*\.\d+|\d+", tax_text)
                if nums:
                    try:
                        tax_amount = float(nums[0])
                        if tax_amount in tax_map:
                            new_tax_id = tax_map[tax_amount]
                            current_tax_ids = odoo_info['taxes_id']
                            
                            # Cập nhật nếu khác
                            if new_tax_id not in current_tax_ids or len(current_tax_ids) > 1:
                                product_model.browse(odoo_info['id']).write({'taxes_id': [(6, 0, [new_tax_id])]})
                                products_updated += 1
                                logs.append(f"   💰 {code}: Set thuế {tax_amount}%")
                    except:
                        pass
            
            # Summary
            logs.append("\n" + "=" * 50)
            logs.append("HOÀN THÀNH!")
            logs.append("=" * 50)
            logs.append(f"💰 Sản phẩm đã cập nhật thuế: {products_updated}")
            logs.append(f"❌ Không tìm thấy trong Odoo: {products_not_found}")

        except Exception as e:
            _logger.exception("Lỗi cập nhật thuế MISA")
            logs.append(f"\n❌ LỖI: {str(e)}")
        
        self.write({
            'log_text': '\n'.join(logs),
            'state': 'done'
        })
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_reset(self):
        """Reset wizard"""
        self.write({'state': 'draft', 'log_text': ''})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
