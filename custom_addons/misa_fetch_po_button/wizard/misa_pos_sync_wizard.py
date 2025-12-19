# -*- coding: utf-8 -*-
"""
Wizard đồng bộ sản phẩm từ MISA CRM vào POS Odoo

Chức năng:
1. Lấy tất cả sản phẩm từ MISA
2. Tự động tạo danh mục POS từ category MISA (giữ cấu trúc phân cấp)
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

    def _create_pos_categories_with_hierarchy(self, misa_categories, logs):
        """
        Tạo danh mục POS với cấu trúc phân cấp đúng.
        
        Args:
            misa_categories: List danh mục từ MISA với thông tin parent
            logs: List để ghi log
            
        Returns:
            dict: Map {category_name_lower: pos.category record}
        """
        pos_categ_model = self.env['pos.category'].sudo()
        categories_created = 0
        
        # Build map: name -> category info
        cat_info_map = {}
        for cat in misa_categories:
            name = (cat.get("name") or "").strip()
            parent = (cat.get("parent") or "").strip()
            if name:
                cat_info_map[name.lower()] = {
                    "name": name,
                    "parent": parent,
                    "id": cat.get("id")
                }
        
        # Map để lưu pos.category đã tạo: name_lower -> record
        created_map = {}
        
        # Lấy tất cả danh mục POS hiện có
        existing_cats = pos_categ_model.search([])
        for cat in existing_cats:
            created_map[cat.name.lower().strip()] = cat
        
        def get_or_create_category(name):
            """Đệ quy tạo category và parent của nó"""
            name_lower = name.lower().strip()
            
            # Đã có trong map -> trả về
            if name_lower in created_map:
                return created_map[name_lower]
            
            # Lấy thông tin từ MISA
            info = cat_info_map.get(name_lower, {"name": name, "parent": ""})
            parent_name = info.get("parent", "").strip()
            
            # Tìm hoặc tạo parent trước
            parent_id = False
            if parent_name:
                parent_cat = get_or_create_category(parent_name)
                if parent_cat:
                    parent_id = parent_cat.id
            
            # Tạo category mới
            new_cat = pos_categ_model.create({
                'name': info.get("name", name),
                'parent_id': parent_id
            })
            created_map[name_lower] = new_cat
            
            nonlocal categories_created
            categories_created += 1
            
            if parent_name:
                logs.append(f"   ➕ Tạo: {info.get('name')} (cha: {parent_name})")
            else:
                logs.append(f"   ➕ Tạo: {info.get('name')} (gốc)")
            
            return new_cat
        
        # Tạo tất cả categories
        for cat in misa_categories:
            name = (cat.get("name") or "").strip()
            if name:
                get_or_create_category(name)
        
        return created_map, categories_created

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
            
            # Lấy danh mục từ MISA (cấu trúc cây)
            logs.append("\n📥 Đang lấy danh mục từ MISA CRM...")
            misa_categories = exporter.fetch_all_categories()
            logs.append(f"✅ Tìm thấy {len(misa_categories)} danh mục trong MISA")
            
            # Lấy sản phẩm từ MISA
            logs.append("\n📥 Đang lấy sản phẩm từ MISA CRM...")
            misa_products = exporter.fetch_all_products()
            logs.append(f"✅ Tìm thấy {len(misa_products)} sản phẩm trong MISA")
            
            # Thống kê
            categories_created = 0
            products_updated = 0
            products_skipped_not_in_pos = 0
            products_not_found = 0
            
            # === BƯỚC 1: TẠO DANH MỤC POS (GIỮ CẤU TRÚC PHÂN CẤP) ===
            cat_map = {}
            if self.sync_mode in ('category_only', 'full'):
                logs.append("\n📁 BƯỚC 1: TẠO DANH MỤC POS (CÓ PHÂN CẤP)")
                logs.append("-" * 30)
                
                cat_map, categories_created = self._create_pos_categories_with_hierarchy(
                    misa_categories, logs
                )
                
                logs.append(f"\n   ✅ Đã tạo {categories_created} danh mục POS mới")
            else:
                # Chỉ build map từ existing categories
                pos_categ_model = self.env['pos.category'].sudo()
                all_pos_cats = pos_categ_model.search([])
                cat_map = {c.name.lower().strip(): c for c in all_pos_cats}
            
            # === BƯỚC 2: GÁN SẢN PHẨM VÀO DANH MỤC ===
            if self.sync_mode in ('product_only', 'full'):
                logs.append("\n📦 BƯỚC 2: GÁN SẢN PHẨM VÀO DANH MỤC POS")
                logs.append("-" * 30)
                logs.append("   (Chỉ xử lý sản phẩm đã bật 'Sẵn sàng trong POS')")
                
                product_model = self.env['product.template'].sudo()
                
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
