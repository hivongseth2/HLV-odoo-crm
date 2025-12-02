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
        help='Tự động đồng bộ giá lên WordPress khi giá thay đổi trong Odoo'
    )

    wordpress_config_id = fields.Many2one(
        'wordpress.config',
        string='Cấu hình WordPress',
        domain=[('active', '=', True)],
        help='Chọn cấu hình WordPress để đồng bộ'
    )

    # ===========================================
    # GET / SET VALUES
    # ===========================================
    @api.model
    def get_values(self):
        res = super().get_values()
        ICP = self.env['ir.config_parameter'].sudo()

        # Auto sync enabled
        auto_sync = ICP.get_param('wordpress_sync.auto_sync_enabled', 'False')
        res['wordpress_auto_sync_enabled'] = auto_sync in ('1', 'true', 'True', True)

        # Default config
        config_id = ICP.get_param('wordpress_sync.default_config_id', '0')
        res['wordpress_config_id'] = int(config_id) if config_id else 0

        return res

    def set_values(self):
        super().set_values()
        ICP = self.env['ir.config_parameter'].sudo()

        ICP.set_param('wordpress_sync.auto_sync_enabled', self.wordpress_auto_sync_enabled)
        ICP.set_param(
            'wordpress_sync.default_config_id',
            self.wordpress_config_id.id if self.wordpress_config_id else 0
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
        config_id = int(ICP.get_param('wordpress_sync.default_config_id', '0') or 0)

        if config_id:
            config = self.env['wordpress.config'].browse(config_id)
            if config.exists() and config.active:
                return config

        # Fallback: lấy config active đầu tiên
        return self.env['wordpress.config'].search([('active', '=', True)], limit=1)
