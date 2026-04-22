# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import json
import logging

_logger = logging.getLogger(__name__)

class MilwaukeeConfig(models.Model):
    _name = 'milwaukee.config'
    _description = 'Milwaukee Pricing Configuration'

    name = fields.Char(string='Tên cấu hình', required=True, default='Cấu hình Milwaukee')
    api_url = fields.Char(string='API Base URL', required=True, default='http://localhost:3000')
    api_key = fields.Char(string='API Key (Optional)', help='Dùng cho môi trường Production nếu có')
    active = fields.Boolean(default=True)

    def action_fetch_products(self):
        """
        Lấy danh sách sản phẩm từ website Milwaukee và map theo SKU vào Odoo.
        """
        self.ensure_one()
        url = f"{self.api_url.rstrip('/')}/api/v1/pricing/products"
        
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            res_data = response.json()
            
            if not res_data.get('success'):
                raise UserError(_("Lỗi từ API: %s") % res_data.get('message', 'Không rõ lỗi'))
            
            products_data = res_data.get('data', [])
            updated_count = 0
            missing_sku = []
            
            for item in products_data:
                sku = item.get('sku')
                milwaukee_id = item.get('id')
                
                if not sku or not milwaukee_id:
                    continue
                
                # Tìm sản phẩm trong Odoo theo SKU (default_code)
                product = self.env['product.template'].search([('default_code', '=', sku)], limit=1)
                if product:
                    product.milwaukee_id = milwaukee_id
                    updated_count += 1
                else:
                    missing_sku.append(sku)
            
            msg = _("Đã đồng bộ ID cho %s sản phẩm.") % updated_count
            if missing_sku:
                msg += _("\nKhông tìm thấy %s SKU trong Odoo: %s") % (len(missing_sku), ", ".join(missing_sku[:10]))
                if len(missing_sku) > 10:
                    msg += "..."
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Kết quả đồng bộ'),
                    'message': msg,
                    'type': 'success' if updated_count > 0 else 'warning',
                    'sticky': False,
                }
            }

        except Exception as e:
            _logger.exception("Lỗi khi fetch sản phẩm Milwaukee")
            raise UserError(_("Không thể kết nối đến API: %s") % str(e))

    def action_push_prices(self):
        """
        Đẩy giá từ Odoo lên website Milwaukee.
        regularPrice: x_studio_ga_web
        salePrice: milwaukee_sale_price
        """
        self.ensure_one()
        
        # Nếu được gọi từ list view (có active_ids), chỉ sync những sản phẩm được chọn
        active_ids = self.env.context.get('active_ids')
        if active_ids and self.env.context.get('active_model') == 'product.template':
            products = self.env['product.template'].browse(active_ids).filtered(lambda p: p.milwaukee_id)
        else:
            # Tìm tất cả sản phẩm đã được map ID
            products = self.env['product.template'].search([('milwaukee_id', '!=', False)])
        
        if not products:
            raise UserError(_("Không tìm thấy sản phẩm nào đã được map Milwaukee ID để đồng bộ."))
        
        payload = []
        for product in products:
            # regularPrice lấy từ x_studio_ga_web
            # Nếu field không tồn tại (do chưa cài Studio hoặc lỗi field), fallback về list_price
            regular_price = getattr(product, 'x_studio_ga_web', 0.0) or product.list_price or 0.0
            
            # salePrice lấy từ milwaukee_sale_price
            sale_price = product.milwaukee_sale_price or None
            
            data = {
                "id": product.milwaukee_id,
                "regularPrice": regular_price,
            }
            if sale_price:
                data["salePrice"] = sale_price
            
            payload.append(data)
            
        if not payload:
            return True

        url = f"{self.api_url.rstrip('/')}/api/v1/pricing/update"
        headers = {
            'Content-Type': 'application/json',
        }
        if self.api_key:
            headers['X-API-Key'] = self.api_key

        try:
            response = requests.patch(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            res_data = response.json()
            
            if res_data.get('success'):
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Thành công'),
                        'message': res_data.get('message', _('Đã cập nhật giá.')),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                raise UserError(_("API báo lỗi: %s") % res_data.get('message', 'Unknown error'))

        except Exception as e:
            _logger.exception("Lỗi khi update giá Milwaukee")
            raise UserError(_("Lỗi khi gửi dữ liệu đến API: %s") % str(e))
