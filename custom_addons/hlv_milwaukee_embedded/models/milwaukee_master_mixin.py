# -*- coding: utf-8 -*-
import requests
import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class MilwaukeeMasterMixin(models.AbstractModel):
    _name = 'milwaukee.master.mixin'
    _description = 'Milwaukee Master API Sync Mixin'

    milwaukee_id = fields.Char(string='Milwaukee ID', copy=False, help="ID của bản ghi trên hệ thống Milwaukee")
    last_sync_date = fields.Datetime(string='Lần đồng bộ cuối', readonly=True, copy=False)

    def _get_master_config(self):
        config = self.env['ir.config_parameter'].sudo()
        base_url = config.get_param('milwaukee.base_url')
        api_key = config.get_param('milwaukee.master_key')
        
        if not base_url or not api_key:
            raise UserError(_("Vui lòng cấu hình Base URL và Master API Key trong Settings!"))
            
        return base_url.rstrip('/'), api_key

    def _push_to_milwaukee(self, entity, data):
        """
        Gửi dữ liệu qua API Master (POST /[entity])
        Hỗ trợ Upsert (ON CONFLICT DO UPDATE trên server Next.js)
        """
        base_url, api_key = self._get_master_config()
        url = f"{base_url}/api/v1/master/{entity}"
        
        headers = {
            'x-api-key': api_key,
            'Content-Type': 'application/json'
        }
        
        try:
            _logger.info("Pushing to Milwaukee [%s]: %s", entity, json.dumps(data))
            response = requests.post(url, json=data, headers=headers, timeout=30)
            response.raise_for_status()
            res_data = response.json()
            
            if not res_data.get('success'):
                error_msg = res_data.get('error', 'Unknown error')
                _logger.error("API Error [%s]: %s", entity, error_msg)
                if not self.env.context.get('milwaukee_sync_silent'):
                    raise UserError(_("Lỗi từ API Milwaukee: %s") % error_msg)
            
            # API trả về dữ liệu đã tạo/cập nhật (mảng hoặc object)
            return res_data.get('data')
            
        except requests.exceptions.RequestException as e:
            _logger.error("Connection Error [%s]: %s", entity, str(e))
            if not self.env.context.get('milwaukee_sync_silent'):
                raise UserError(_("Không thể kết nối đến API Milwaukee. Vui lòng kiểm tra Server và Base URL."))
        except Exception as e:
            _logger.error("Unexpected Error [%s]: %s", entity, str(e))
            if not self.env.context.get('milwaukee_sync_silent'):
                raise UserError(_("Lỗi không mong muốn: %s") % str(e))

    def action_milwaukee_push(self):
        """Action trigger tay từ button"""
        self.ensure_one()
        self._sync_to_milwaukee()

    def _sync_to_milwaukee(self):
        """Phải được override bởi các model cụ thể"""
        pass
