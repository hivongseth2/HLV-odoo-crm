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
