# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from .wordpress_api import StockSyncService
import logging

_logger = logging.getLogger(__name__)


class WordPressComboStockSync(models.TransientModel):
    """
    Wizard để cập nhật tình trạng kho của combo dựa trên BOM
    và đồng bộ lên WordPress
    """
    _name = 'wordpress.combo.stock.sync'
    _description = 'WordPress Combo Stock Sync Wizard'

    # ===========================================
    # FIELDS
    # ===========================================
    sync_mode = fields.Selection([
        ('all_combos', 'Tất cả Combo (có BOM)'),
        ('out_of_stock_child', 'Combo có sản phẩm con hết hàng'),
        ('selected', 'Sản phẩm đã chọn'),
    ], string='Chế độ đồng bộ', default='out_of_stock_child', required=True)

    product_ids = fields.Many2many(
        'product.template',
        string='Sản phẩm',
        help='Danh sách sản phẩm cần đồng bộ stock (chỉ dùng với chế độ "Sản phẩm đã chọn")'
    )

    wordpress_config_id = fields.Many2one(
        'wordpress.config',
        string='Cấu hình WordPress',
        default=lambda self: self._default_wordpress_config(),
        domain=[('active', '=', True)],
        required=True
    )

    # Info fields
    preview_info = fields.Text(
        string='Thông tin',
        compute='_compute_preview_info'
    )

    # ===========================================
    # DEFAULTS & COMPUTES
    # ===========================================
    @api.model
    def _default_wordpress_config(self):
        """Lấy config mặc định"""
        ICP = self.env['ir.config_parameter'].sudo()
        config_id = ICP.get_param('wordpress_sync.default_config_id', False)

        if config_id:
            try:
                config = self.env['wordpress.config'].browse(int(config_id))
                if config.exists() and config.active:
                    return config.id
            except (ValueError, TypeError):
                pass

        config = self.env['wordpress.config'].search([('active', '=', True)], limit=1)
        return config.id if config else False

    @api.depends('sync_mode')
    def _compute_preview_info(self):
        """Hiển thị thông tin preview"""
        for wizard in self:
            if wizard.sync_mode == 'all_combos':
                count = self._count_combo_products()
                wizard.preview_info = f"Sẽ kiểm tra và đồng bộ {count} combo có BOM"
            elif wizard.sync_mode == 'out_of_stock_child':
                combos = self._find_combos_with_out_of_stock_child()
                wizard.preview_info = f"Tìm thấy {len(combos)} combo có sản phẩm con hết hàng"
            else:
                count = len(wizard.product_ids) if wizard.product_ids else 0
                wizard.preview_info = f"Đã chọn {count} sản phẩm"

    # ===========================================
    # HELPER METHODS
    # ===========================================
    def _get_stock_field(self):
        """Get configured stock field name from wordpress.config"""
        if self.wordpress_config_id:
            return self.wordpress_config_id.stock_status_field or 'qty_available'
        return 'qty_available'

    def _is_product_in_stock(self, product_tmpl):
        """Kiểm tra product.template còn hàng không"""
        stock_field = self._get_stock_field()
        total_qty = 0
        for variant in product_tmpl.product_variant_ids:
            qty = getattr(variant, stock_field, 0) or 0
            total_qty += qty
        return total_qty > 0

    def _count_combo_products(self):
        """Đếm số lượng combo có BOM (phantom type)"""
        return self.env['mrp.bom'].search_count([
            ('type', '=', 'phantom'),
            ('active', '=', True)
        ])

    def _get_all_combo_products(self):
        """Lấy tất cả product template là combo (có BOM phantom)"""
        boms = self.env['mrp.bom'].search([
            ('type', '=', 'phantom'),
            ('active', '=', True)
        ])
        return boms.mapped('product_tmpl_id')

    def _find_combos_with_out_of_stock_child(self):
        """
        Tìm tất cả combo có ít nhất 1 sản phẩm con hết hàng

        Returns:
            recordset: product.template của các combo bị ảnh hưởng
        """
        affected_combos = self.env['product.template']

        # Lấy tất cả BOM phantom
        boms = self.env['mrp.bom'].search([
            ('type', '=', 'phantom'),
            ('active', '=', True)
        ])

        for bom in boms:
            # Kiểm tra từng component trong BOM
            for line in bom.bom_line_ids:
                child_product = line.product_id.product_tmpl_id
                if not self._is_product_in_stock(child_product):
                    # Có component hết hàng -> combo này bị ảnh hưởng
                    affected_combos |= bom.product_tmpl_id
                    break  # Không cần kiểm tra các component khác

        return affected_combos

        return affected_combos

    def _get_oos_reason(self, combo):
        """
        Identify which children are Out of Stock
        """
        reasons = []
        bom = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', combo.id), 
            ('type', '=', 'phantom'), 
            ('active', '=', True)
        ], limit=1)
        
        if bom:
            for line in bom.bom_line_ids:
                child = line.product_id.product_tmpl_id
                if not self._is_product_in_stock(child):
                    reasons.append(child.name)
        
        if reasons:
            return f"Cập nhật do SP con hết hàng: {', '.join(reasons)}"
        return "Cập nhật stock combo (Auto)"

    def _find_parent_combos(self, product_tmpl):
        """
        Tìm tất cả combo cha chứa sản phẩm này (qua BOM)

        Args:
            product_tmpl: product.template record

        Returns:
            recordset: product.template của các combo cha
        """
        parent_combos = self.env['product.template']

        # Tìm tất cả BOM lines chứa product này (hoặc variants của nó)
        product_variants = product_tmpl.product_variant_ids
        bom_lines = self.env['mrp.bom.line'].search([
            ('product_id', 'in', product_variants.ids)
        ])

        # Lấy BOM cha và filter chỉ lấy phantom type
        for line in bom_lines:
            bom = line.bom_id
            if bom.type == 'phantom' and bom.active:
                parent_combos |= bom.product_tmpl_id

        return parent_combos

    def _determine_combo_stock_status(self, combo_product):
        """
        Xác định tình trạng kho của combo dựa trên các component

        Args:
            combo_product: product.template record (combo)

        Returns:
            str: 'instock' hoặc 'outofstock'
        """
        bom = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', combo_product.id),
            ('type', '=', 'phantom'),
            ('active', '=', True)
        ], limit=1)

        if not bom:
            # Không có BOM, sử dụng stock trực tiếp của sản phẩm
            return 'instock' if self._is_product_in_stock(combo_product) else 'outofstock'

        # Kiểm tra tất cả component
        for line in bom.bom_line_ids:
            child_product = line.product_id.product_tmpl_id
            if not self._is_product_in_stock(child_product):
                return 'outofstock'

        return 'instock'

    # ===========================================
    # ACTIONS
    # ===========================================
    def action_sync(self):
        """Thực hiện đồng bộ stock status"""
        self.ensure_one()

        # Validate WordPress config
        wc_key, wc_secret = self.wordpress_config_id.get_credentials()
        if not wc_key or not wc_secret:
            return self._notify('Thiếu Credentials', 'Vui lòng nhập Consumer Key và Secret', 'warning')

        # Xác định danh sách sản phẩm cần sync
        if self.sync_mode == 'all_combos':
            products = self._get_all_combo_products()
        elif self.sync_mode == 'out_of_stock_child':
            products = self._find_combos_with_out_of_stock_child()
        else:  # selected
            products = self.product_ids

        if not products:
            return self._notify('Không có sản phẩm', 'Không tìm thấy sản phẩm nào để đồng bộ', 'warning')

        # Thực hiện sync
        service = StockSyncService(self.env, self.wordpress_config_id)

        success_count = 0
        failed_count = 0
        results_log = []

        for product in products:
            try:
                result = service.sync_stock_status(product)

                if result['success']:
                    success_count += 1
                    results_log.append(f"✓ {product.name}: {result['stock_status']}")

                    # Tạo log
                    self.env['product.sync.log'].create_log(
                        product=product,
                        status='success',
                        message=f"Combo Stock: {result['message']}",
                        sync_type='manual',
                        sku=result.get('sku', ''),
                        wc_product_id=result.get('wc_product_id', '')
                    )
                else:
                    failed_count += 1
                    results_log.append(f"✗ {product.name}: {result['message']}")

                    self.env['product.sync.log'].create_log(
                        product=product,
                        status='failed',
                        message=f"Combo Stock: {result['message']}",
                        sync_type='manual',
                        sku=result.get('sku', product.default_code or ''),
                        wc_product_id=result.get('wc_product_id', '')
                    )

            except Exception as e:
                failed_count += 1
                results_log.append(f"✗ {product.name}: {str(e)}")
                _logger.exception(f"Error syncing combo stock for {product.name}: {e}")

        # Hiện thông báo kết quả
        message = f"Thành công: {success_count}, Thất bại: {failed_count}"
        if failed_count > 0:
            message += f"\n\nChi tiết:\n" + "\n".join(results_log[-10:])  # Show last 10

        return self._notify(
            'Kết quả đồng bộ Stock Combo',
            message,
            'success' if failed_count == 0 else 'warning'
        )

    def action_update_all_parent_combos(self):
        """
        Action đặc biệt: Tìm tất cả sản phẩm hết hàng và cập nhật combo cha

        Flow:
        1. Tìm tất cả sản phẩm hết hàng
        2. Với mỗi sản phẩm hết hàng, tìm combo cha
        3. Cập nhật tình trạng combo cha thành hết hàng
        4. Sync lên WordPress
        """
        self.ensure_one()

        # Validate WordPress config
        wc_key, wc_secret = self.wordpress_config_id.get_credentials()
        if not wc_key or not wc_secret:
            return self._notify('Thiếu Credentials', 'Vui lòng nhập Consumer Key và Secret', 'warning')

        # Tìm tất cả combo bị ảnh hưởng
        affected_combos = self._find_combos_with_out_of_stock_child()

        if not affected_combos:
            return self._notify('Không có combo bị ảnh hưởng',
                              'Không tìm thấy combo nào có sản phẩm con hết hàng', 'info')

        # Sync (job này đi tới đúng site đã chọn trong wizard, không phải site mặc định)
        QueueModel = self.env['wordpress.sync.queue']
        success_count = 0
        for combo in affected_combos:
            reason = self._get_oos_reason(combo)
            QueueModel.create_job(
                combo, sync_type='stock', priority=20, initial_log=reason,
                config_id=self.wordpress_config_id.id,
            )
            success_count += 1

        return self._notify(
            'Đã tạo yêu cầu cập nhật',
            f"Đã thêm {success_count} combo vào hàng đợi cập nhật tồn kho.",
            'success'
        )

    @api.model
    def cron_auto_check_combo_stock(self):
        """
        Cron Job: Tự động kiểm tra và cập nhật stock cho combo

        Multi-site: mỗi combo có thể được gắn nhiều site (wordpress_config_ids).
        Job chỉ được tạo cho site nào thực sự bật "Tự động đồng bộ stock combo"
        (auto_sync_combo_stock), thay vì chỉ xét site mặc định như trước.
        """
        # 1. Kiểm tra có ít nhất 1 site nào bật auto_sync_combo_stock không
        config = self._default_wordpress_config()
        if not config:
            return

        # 2. Tìm combo bị ảnh hưởng
        wizard = self.create({'sync_mode': 'out_of_stock_child', 'wordpress_config_id': config})
        affected_combos = wizard._find_combos_with_out_of_stock_child()

        if not affected_combos:
            _logger.info("Cron Combo Stock: No affected combos found.")
            return

        _logger.info(f"Cron Combo Stock: Found {len(affected_combos)} combos to update.")

        # 3. Queue jobs - chỉ cho site nào của combo có bật auto_sync_combo_stock
        QueueModel = self.env['wordpress.sync.queue']
        for combo in affected_combos:
            target_configs = combo._get_target_wordpress_configs().filtered('auto_sync_combo_stock')
            if not target_configs:
                continue
            reason = self._get_oos_reason(combo)
            for target_config in target_configs:
                QueueModel.create_job(
                    combo, sync_type='stock', priority=15, initial_log=reason,
                    config_id=target_config.id,
                )

    # ===========================================
    # HELPER
    # ===========================================
    def _notify(self, title, message, notif_type='info'):
        """Hiển thị notification"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notif_type,
                'sticky': True,
            }
        }
