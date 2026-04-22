# -*- coding: utf-8 -*-
from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Define Studio fields explicitly to avoid view errors during module load
    x_studio_gi_web = fields.Monetary(string="Giá Web")
    x_studio_ga_hng_nim_yt = fields.Monetary(string="Giá Niêm Yết")

    milwaukee_id = fields.Char(
        string='Milwaukee Product ID',
        help='ID of this product on the Milwaukee pricing website',
        copy=False,
        index=True
    )

    def action_milwaukee_fast_sync(self):
        """Đồng bộ nhanh trực tiếp 1 sản phẩm từ danh sách"""
        self.ensure_one()
        api_url = self.env['ir.config_parameter'].sudo().get_param('hlv_milwaukee_price_sync.api_url')
        if not api_url:
            from odoo.exceptions import UserError
            raise UserError("Chưa cấu hình Milwaukee API URL. Vui lòng thiết lập trong Inventory > Configuration > Settings.")
        
        return self.action_push_prices_to_milwaukee(api_url)

    def action_push_prices_to_milwaukee(self, api_url):
        """Helper để đẩy giá các sản phẩm hiện tại lên Milwaukee API"""
        products = self.filtered(lambda p: p.milwaukee_id)
        if not products:
             from odoo.exceptions import UserError
             raise UserError("Không có sản phẩm nào đã được map với Milwaukee để đồng bộ.")
             
        api_key = self.env['ir.config_parameter'].sudo().get_param('hlv_milwaukee_price_sync.api_key')

        import requests
        payload = []
        for product in products:
            # Giá Niêm Yết -> regularPrice
            reg_price = getattr(product, 'x_studio_ga_hng_nim_yt', 0.0)
            # Dứt khoát lấy 0 nếu là 0, không fallback
            reg_price = float(reg_price or 0.0)
            
            # Giá Web -> salePrice
            sale_price = getattr(product, 'x_studio_gi_web', 0.0)
            sale_price = float(sale_price or 0.0)
            
            data = {
                "id": product.milwaukee_id,
                "regularPrice": reg_price,
            }
            if sale_price > 0:
                data["salePrice"] = sale_price
            else:
                data["salePrice"] = 0
            
            payload.append(data)
            
        url = f"{api_url.rstrip('/')}/api/v1/pricing/update"
        headers = {'Content-Type': 'application/json'}
        if api_key: 
            headers['X-API-Key'] = api_key
        
        try:
             response = requests.patch(url, json=payload, headers=headers, timeout=30)
             response.raise_for_status()
             res_data = response.json()
             
             if res_data.get('success'):
                 from odoo import _
                 return {
                     'type': 'ir.actions.client',
                     'tag': 'display_notification',
                     'params': {
                         'title': _('Thành công'),
                         'message': res_data.get('message', _('Đã cập nhật giá Milwaukee thành công.')),
                         'type': 'success',
                         'sticky': False,
                     }
                 }
             else:
                 from odoo.exceptions import UserError
                 raise UserError(_("API báo lỗi: %s") % res_data.get('message', 'Unknown error'))

        except Exception as e:
             from odoo.exceptions import UserError
             raise UserError("Lỗi khi gửi dữ liệu đến API Milwaukee: %s" % str(e))

