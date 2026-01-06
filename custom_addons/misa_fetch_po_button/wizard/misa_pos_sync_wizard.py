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
import re

_logger = logging.getLogger(__name__)


class MisaPosProductSyncWizard(models.TransientModel):
    _name = 'misa.pos.product.sync.wizard'
    _description = 'Đồng bộ sản phẩm MISA vào POS'

    sync_mode = fields.Selection([
        ('category_only', 'Chỉ tạo danh mục POS'),
        ('product_only', 'Chỉ gán sản phẩm vào danh mục'),
        ('full', 'Đầy đủ (Tạo danh mục + Gán sản phẩm)'),
    ], string='Chế độ đồng bộ', default='full', required=True)

    auto_update_tax = fields.Boolean(string='Cập nhật thuế theo MISA', default=False,
                                   help='Tự động tìm thuế trong Odoo theo % từ MISA và cập nhật vào sản phẩm')
    
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
            products_skipped_not_in_pos = 0
            products_not_found = 0
            products_tax_updated = 0
            
            # Cache taxes if needed
            tax_map = {} # amount -> tax_id
            if self.auto_update_tax:
                # Lấy tất cả thuế bán ra
                taxes = self.env['account.tax'].search([('type_tax_use', '=', 'sale')])
                for t in taxes:
                    # Map theo update amount (float)
                    # Lưu ý: Có thể có nhiều thuế cùng %, ta lấy cái đầu tiên tìm thấy hoặc cần logic complex hơn
                    # Ở đây lấy cái đầu tiên tìm thấy matching amount
                    if t.amount not in tax_map:
                        tax_map[t.amount] = t.id
            
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
            
            # === BƯỚC 2: GÁN SẢN PHẨM VÀO DANH MỤC POS ===
            if self.sync_mode in ('product_only', 'full'):
                logs.append("\n📦 BƯỚC 2: GÁN SẢN PHẨM VÀO DANH MỤC POS")
                logs.append("-" * 30)
                logs.append("   (Chỉ xử lý sản phẩm đã bật 'Sẵn sàng trong POS')")
                
                # 1. LOAD TOÀN BỘ SẢN PHẨM ODOO VÀO BỘ NHỚ (Chỉ lấy field cần thiết)
                logs.append("\n   ⏳ Đang tải danh sách sản phẩm Odoo...")
                product_model = self.env['product.template'].sudo()
                
                # Domain tìm kiếm sản phẩm:
                # Nếu update tax -> tìm tất cả sản phẩm
                # Nếu không -> chỉ tìm sản phẩm available_in_pos
                domain = [('default_code', '!=', False)]
                if not self.auto_update_tax:
                    domain.append(('available_in_pos', '=', True))
                    
                odoo_products = product_model.search_read(
                    domain,
                    ['default_code', 'pos_categ_ids', 'taxes_id']
                )
                
                # Map nhanh: Code -> Record ID & Current Categories
                odoo_map = {}
                for p in odoo_products:
                    code = p['default_code'].strip()
                    odoo_map[code] = {
                        'id': p['id'],
                        'pos_categ_ids': p['pos_categ_ids'],
                        'taxes_id': p['taxes_id']
                    }
                
                logs.append(f"   ✅ Đã tải được {len(odoo_map)} sản phẩm Odoo vào bộ nhớ.")

                # 3. FETCH MISA PRODUCTS (CHỈ LẤY CỘT CẦN THIẾT)
                logs.append("\n   ⏳ Đang tải danh sách sản phẩm MISA (Tối ưu)...")
                # Chỉ lấy ProductCode, ProductCategoryIDText và Tax info
                # "ProductCode,ProductCategoryIDText,TaxID,TaxIDText"
                # Base64: UHJvZHVjdENvZGUsUHJvZHVjdENhdGVnb3J5SURUZXh0LFRheElELFRheElEVGV4dA==
                
                minimal_columns = "UHJvZHVjdENvZGUsUHJvZHVjdENhdGVnb3J5SURUZXh0LFRheElELFRheElEVGV4dA=="
                misa_products = exporter.fetch_all_products(page_size=1000, columns=minimal_columns)
                logs.append(f"   ✅ Đã tải {len(misa_products)} sản phẩm từ MISA.")
                
                # 3. MATCH & UPDATE
                logs.append("\n   🔄 Đang đối chiếu và cập nhật...")
                
                for p in misa_products:
                    code = (p.get("ProductCode") or "").strip()
                    cat_name = (p.get("ProductCategoryIDText") or "").strip()
                    
                    if not code or not cat_name:
                        continue
                    
                    # Tìm trong Odoo Map (O(1) lookup)
                    if code not in odoo_map:
                        products_not_found += 1
                        continue
                        
                    odoo_info = odoo_map[code]
                    
                    # Tìm danh mục POS
                    if cat_name.lower().strip() not in cat_map:
                        continue
                        
                    pos_cat = cat_map[cat_name.lower().strip()]
                    
                    # Cập nhật danh mục POS
                    current_categ_ids = odoo_info['pos_categ_ids']
                    if pos_cat.id not in current_categ_ids:
                        product_model.browse(odoo_info['id']).write({'pos_categ_ids': [(4, pos_cat.id)]})
                        products_updated += 1
                        logs.append(f"   ✏️  {code} → {cat_name}")

                    # Cập nhật thuế (nếu được chọn)
                    if self.auto_update_tax:
                        tax_text = str(p.get("TaxIDText") or "")
                        # Parse số từ string, ví dụ "8.0%" hoặc "8%" -> 8.0
                        # Regex tìm số thực
                        nums = re.findall(r"[-+]?\d*\.\d+|\d+", tax_text)
                        if nums:
                            try:
                                tax_amount = float(nums[0])
                                # Tìm tax id trong map
                                if tax_amount in tax_map:
                                    new_tax_id = tax_map[tax_amount]
                                    current_tax_ids = odoo_info['taxes_id']
                                    
                                    # Nếu chưa có thuế này hoặc thuế hiện tại khác (ở đây thay thế hoàn toàn nếu khác)
                                    # Logic: Replace existing taxes with new tax if not present?
                                    # Yêu cầu: "thực hiện cập nhật vat cho toàn bộ sản phẩm"
                                    # -> Set thuế = thuế tìm được.
                                    
                                    if new_tax_id not in current_tax_ids or len(current_tax_ids) > 1:
                                        # Chỉ update nếu khác biệt
                                        # Ở đây ta set đè (6, 0, [ids]) để đảm bảo đúng thuế duy nhất
                                        product_model.browse(odoo_info['id']).write({'taxes_id': [(6, 0, [new_tax_id])]})
                                        products_tax_updated += 1
                                        if products_updated == 0: # Tránh log duplicate nếu đã log ở trên (tuy nhiên log trên là category)
                                            # Chúng ta nên log riêng cho rõ
                                            pass
                                        logs.append(f"   💰 {code} cập nhật thuế: {tax_amount}%")
                            except:
                                pass
                
                logs.append(f"\n   ✅ Đã cập nhật xong: {products_updated} sản phẩm")
                logs.append(f"   (Không tìm thấy code tương ứng trong danh sách POS Odoo: {products_not_found})")
            
            # Tổng kết
            logs.append("\n" + "=" * 50)
            logs.append("HOÀN THÀNH!")
            logs.append("=" * 50)
            logs.append(f"📁 Danh mục POS tạo mới: {categories_created}")
            logs.append(f"📦 Sản phẩm được gán danh mục: {products_updated}")
            logs.append(f"💰 Sản phẩm được cập nhật thuế: {products_tax_updated}")
            logs.append(f"⏭️  Bỏ qua (chưa bật POS và không update tax): {products_skipped_not_in_pos}")
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
