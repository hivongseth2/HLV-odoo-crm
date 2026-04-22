# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import logging

_logger = logging.getLogger(__name__)

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    milwaukee_api_url = fields.Char(
        string='API Base URL',
        config_parameter='hlv_milwaukee_price_sync.api_url',
        help="Ví dụ: http://localhost:3000 hoặc URL từ Pinggy"
    )
    milwaukee_api_key = fields.Char(
        string='API Key (Tùy chọn)',
        config_parameter='hlv_milwaukee_price_sync.api_key'
    )

    def action_fetch_milwaukee_products(self):
        """Lấy danh sách sản phẩm từ website Milwaukee, map ID và cập nhật giá vào Odoo"""
        
        config = self.env['ir.config_parameter'].sudo()
        # Ưu tiên lấy giá trị từ form hiện tại (trường hợp user chưa bấm Lưu)
        api_url = self.milwaukee_api_url or config.get_param('hlv_milwaukee_price_sync.api_url')
        
        if not api_url:
            raise UserError(_("Vui lòng thiết lập API Base URL!"))
            
        url = f"{api_url.rstrip('/')}/api/v1/pricing/products"
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            res_data = response.json()
            
            if not res_data.get('success'):
                raise UserError(_("Lỗi từ API: %s") % res_data.get('message', 'Không rõ nguyên nhân'))
            
            products_data = res_data.get('data', [])
            updated_count = 0
            missing_sku = []
            
            for item in products_data:
                sku = item.get('sku')
                milwaukee_id = item.get('id')
                reg_price = item.get('regularPrice', 0.0)
                sale_price = item.get('salePrice', 0.0)
                
                if not sku or not milwaukee_id:
                    continue
                
                product = self.env['product.template'].search([('default_code', '=', sku)], limit=1)
                if product:
                    product.milwaukee_id = str(milwaukee_id)
                    # Cập nhật giá từ Milwaukee về Odoo
                    if reg_price is not None:
                        product.x_studio_ga_hng_nim_yt = float(reg_price)
                    if sale_price is not None:
                        product.x_studio_gi_web = float(sale_price)
                        
                    updated_count += 1
                else:
                    missing_sku.append(sku)
            
            msg = _("Đã lấy ID và đồng bộ Giá cho %s sản phẩm.") % updated_count
            if missing_sku:
                msg += _("\nLưu ý: Không tìm thấy %s SKU trong Odoo. (Ví dụ: %s)") % (
                    len(missing_sku), ", ".join(missing_sku[:5]))
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Kết quả đồng bộ Milwaukee'),
                    'message': msg,
                    'type': 'success' if updated_count > 0 else 'warning',
                    'sticky': True,
                }
            }

        except Exception as e:
            _logger.exception("Lỗi khi fetch sản phẩm Milwaukee")
            raise UserError(_("Không thể kết nối API. Chi tiết: %s") % str(e))
