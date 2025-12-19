# -*- coding: utf-8 -*-
"""
Wizard đồng bộ sản phẩm từ MISA CRM vào POS Odoo

Chức năng:
1. Lấy tất cả sản phẩm từ MISA
2. Tự động tạo danh mục POS từ category MISA (nếu chưa có) 
3. Tìm sản phẩm trong Odoo theo code, nếu đã bật available_in_pos thì gán vào danh mục POS
"""
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class MisaPosProductSyncWizard(models.TransientModel):
    _name = 'misa.pos.product.sync.wizard'
    _description = 'Đồng bộ sản phẩm MISA vào POS'

    sync_mode = fields.Selection([
        ('category_only', 'Chỉ tạo danh mục POS'),
        ('product_only', 'Chỉ gán sản phẩm vào danh mục'),
        ('full', 'Đầy đủ (Tạo danh mục + Gán sản phẩm)'),
    ], string='Chế độ đồng bộ', default='full', required=True)
    
    log_text = fields.Text(string='Kết quả', readonly=True)
    state = fields.Selection([
        ('draft', 'Chuẩn bị'),
        ('done', 'Hoàn thành')
    ], default='draft')

    def action_sync(self):
        """Thực hiện đồng bộ"""
        self.ensure_one()
        
        logs = []
        logs.append("=" * 50)
        logs.append("ĐỒNG BỘ SẢN PHẨM MISA → POS")
        logs.append("=" * 50)
        
        try:
            # Import exporter
            from odoo.addons.misa_fetch_po_button.utils.misa_product_export import MisaProductExporter
            
            exporter = MisaProductExporter(self.env)
            
            # Lấy sản phẩm từ MISA
            logs.append("\n📥 Đang lấy sản phẩm từ MISA CRM...")
            misa_products = exporter.fetch_all_products()
            logs.append(f"✅ Tìm thấy {len(misa_products)} sản phẩm trong MISA")
            
            # Thống kê
            categories_created = 0
            products_updated = 0
            products_skipped_not_in_pos = 0
            products_not_found = 0
            
            # === BƯỚC 1: TẠO DANH MỤC POS ===
            if self.sync_mode in ('category_only', 'full'):
                logs.append("\n📁 BƯỚC 1: TẠO DANH MỤC POS")
                logs.append("-" * 30)
                
                # Lấy tất cả category duy nhất từ sản phẩm MISA
                misa_categories = set()
                for p in misa_products:
                    cat_name = (p.get("ProductCategoryIDText") or "").strip()
                    if cat_name:
                        misa_categories.add(cat_name)
                
                logs.append(f"   Tìm thấy {len(misa_categories)} danh mục trong MISA")
                
                # Tạo danh mục POS nếu chưa có
                pos_categ_model = self.env['pos.category'].sudo()
                
                for cat_name in misa_categories:
                    existing = pos_categ_model.search([('name', '=ilike', cat_name)], limit=1)
                    if not existing:
                        pos_categ_model.create({'name': cat_name})
                        categories_created += 1
                        logs.append(f"   ➕ Tạo mới: {cat_name}")
                
                logs.append(f"\n   ✅ Đã tạo {categories_created} danh mục POS mới")
            
            # === BƯỚC 2: GÁN SẢN PHẨM VÀO DANH MỤC ===
            if self.sync_mode in ('product_only', 'full'):
                logs.append("\n📦 BƯỚC 2: GÁN SẢN PHẨM VÀO DANH MỤC POS")
                logs.append("-" * 30)
                logs.append("   (Chỉ xử lý sản phẩm đã bật 'Sẵn sàng trong POS')")
                
                product_model = self.env['product.template'].sudo()
                pos_categ_model = self.env['pos.category'].sudo()
                
                # Build map category name -> pos.category record
                all_pos_cats = pos_categ_model.search([])
                cat_map = {c.name.lower().strip(): c for c in all_pos_cats}
                
                for p in misa_products:
                    code = (p.get("ProductCode") or "").strip()
                    cat_name = (p.get("ProductCategoryIDText") or "").strip()
                    
                    if not code or not cat_name:
                        continue
                    
                    # Tìm sản phẩm trong Odoo theo default_code
                    odoo_product = product_model.search([('default_code', '=', code)], limit=1)
                    
                    if not odoo_product:
                        products_not_found += 1
                        continue
                    
                    # CHỈ xử lý sản phẩm đã có available_in_pos = True
                    if not odoo_product.available_in_pos:
                        products_skipped_not_in_pos += 1
                        continue
                    
                    # Tìm danh mục POS tương ứng
                    if cat_name.lower().strip() not in cat_map:
                        continue
                    
                    pos_cat = cat_map[cat_name.lower().strip()]
                    
                    # Kiểm tra xem đã có danh mục này chưa
                    if pos_cat.id not in odoo_product.pos_categ_ids.ids:
                        odoo_product.write({'pos_categ_ids': [(4, pos_cat.id)]})
                        products_updated += 1
                        logs.append(f"   ✏️  {code} → {cat_name}")
                
                logs.append(f"\n   ✅ Đã gán {products_updated} sản phẩm vào danh mục")
                logs.append(f"   ⏭️  Bỏ qua {products_skipped_not_in_pos} sản phẩm (chưa bật POS)")
                logs.append(f"   ❌ Không tìm thấy {products_not_found} sản phẩm trong Odoo")
            
            # Tổng kết
            logs.append("\n" + "=" * 50)
            logs.append("HOÀN THÀNH!")
            logs.append("=" * 50)
            logs.append(f"📁 Danh mục POS tạo mới: {categories_created}")
            logs.append(f"📦 Sản phẩm được gán danh mục: {products_updated}")
            logs.append(f"⏭️  Bỏ qua (chưa bật POS): {products_skipped_not_in_pos}")
            logs.append(f"❌ Không tìm thấy trong Odoo: {products_not_found}")
            
        except Exception as e:
            _logger.exception("Lỗi đồng bộ MISA → POS")
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
