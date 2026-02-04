# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    """
    Settings cho WordPress Sync trong Inventory Settings
    """
    _inherit = 'res.config.settings'

    # ===========================================
    # FIELDS
    # ===========================================
    wordpress_auto_sync_enabled = fields.Boolean(
        string='Bật đồng bộ giá tự động',
        help='Tự động đồng bộ giá lên WordPress khi giá thay đổi trong Odoo',
        config_parameter='wordpress_sync.auto_sync_enabled'
    )

    wordpress_config_id = fields.Many2one(
        'wordpress.config',
        string='Cấu hình WordPress',
        domain=[('active', '=', True)],
        help='Chọn cấu hình WordPress để đồng bộ',
        config_parameter='wordpress_sync.default_config_id'
    )

    # === COMBO PRICING SETTINGS ===
    wp_combo_pricing_method = fields.Selection([
        ('sum_combo_price', 'Cộng giá bán trong combo'),
        ('discount_percentage', 'Tổng giá giảm %'),
    ], string='Phương pháp tính giá combo',
       default='sum_combo_price',
       config_parameter='wordpress_sync.combo_pricing_method',
       help='Chọn phương pháp tính giá bán cho sản phẩm combo (dựa trên BOM)')

    wp_combo_discount_percentage = fields.Float(
        string='Phần trăm giảm giá combo (%)',
        default=0.0,
        config_parameter='wordpress_sync.combo_discount_percentage',
        help='Phần trăm giảm giá khi tính giá combo (VD: 10 = giảm 10%)'
    )

    # === STOCK STATUS SETTINGS ===
    wp_stock_status_field = fields.Selection([
        ('qty_available', 'Số lượng hiện có (qty_available)'),
        ('virtual_available', 'Số lượng dự kiến (virtual_available)'),
        ('free_qty', 'Số lượng khả dụng (free_qty)'),
    ], string='Trường xác định tình trạng kho',
       default='qty_available',
       config_parameter='wordpress_sync.stock_status_field',
       help='Chọn trường để xác định sản phẩm còn hàng hay hết hàng')

    wp_auto_sync_combo_stock = fields.Boolean(
        string='Tự động cập nhật tình trạng combo',
        default=False,
        config_parameter='wordpress_sync.auto_sync_combo_stock',
        help='Tự động cập nhật tình trạng kho của combo khi sản phẩm con thay đổi'
    )

    # ===========================================
    # HELPER METHODS
    # ===========================================
    @api.model
    def is_auto_sync_enabled(self):
        """
        Kiểm tra auto-sync có được bật không

        Returns:
            bool: True nếu auto-sync enabled
        """
        ICP = self.env['ir.config_parameter'].sudo()
        value = ICP.get_param('wordpress_sync.auto_sync_enabled', 'False')
        return value in ('1', 'true', 'True', True)

    @api.model
    def get_default_config(self):
        """
        Lấy config WordPress mặc định

        Returns:
            wordpress.config record hoặc False
        """
        ICP = self.env['ir.config_parameter'].sudo()
        config_id = ICP.get_param('wordpress_sync.default_config_id', False)

        if config_id:
            try:
                config = self.env['wordpress.config'].browse(int(config_id))
                if config.exists() and config.active:
                    return config
            except (ValueError, TypeError):
                pass

        # Fallback: lấy config active đầu tiên
        return self.env['wordpress.config'].search([('active', '=', True)], limit=1)

    @api.model
    def get_combo_pricing_method(self):
        """
        Lấy phương pháp tính giá combo

        Returns:
            str: 'sum_combo_price' hoặc 'discount_percentage'
        """
        ICP = self.env['ir.config_parameter'].sudo()
        return ICP.get_param('wordpress_sync.combo_pricing_method', 'sum_combo_price')

    @api.model
    def get_combo_discount_percentage(self):
        """
        Lấy phần trăm giảm giá combo

        Returns:
            float: Phần trăm giảm giá (0-100)
        """
        ICP = self.env['ir.config_parameter'].sudo()
        try:
            return float(ICP.get_param('wordpress_sync.combo_discount_percentage', '0'))
        except (ValueError, TypeError):
            return 0.0

    @api.model
    def get_stock_status_field(self):
        """
        Lấy field xác định tình trạng kho

        Returns:
            str: Tên field ('qty_available', 'virtual_available', 'free_qty')
        """
        ICP = self.env['ir.config_parameter'].sudo()
        return ICP.get_param('wordpress_sync.stock_status_field', 'qty_available')

