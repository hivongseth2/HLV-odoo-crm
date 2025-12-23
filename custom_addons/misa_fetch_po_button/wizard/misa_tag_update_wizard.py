from odoo import models, fields, api, _

class MisaTagUpdateWizard(models.TransientModel):
    _name = 'misa.tag.update.wizard'
    _description = 'Wizard cập nhật Tag từ địa chỉ'

    from_date = fields.Date(string="Từ ngày", required=True, default=fields.Date.context_today)
    to_date = fields.Date(string="Đến ngày", required=True, default=fields.Date.context_today)

    def action_update_tags(self):
        self.ensure_one()
        # Tìm các đơn hàng trong khoảng thời gian
        # domain: date_order trong khoảng, và có địa chỉ giao hàng
        orders = self.env['sale.order'].search([
            ('date_order', '>=', self.from_date),
            ('date_order', '<=', self.to_date),
            ('state', '!=', 'cancel'), # Có thể update cả đơn cancel nếu cần? Thường là không.
        ])

        count = 0
        misa_utils = self.env['misa.api.utils']
        
        for order in orders:
            # Lấy địa chỉ giao hàng. 
            # Ưu tiên partner_shipping_id.street, hoặc fallback khác nếu cần.
            # Trong logic sync cũ: shipping_address_str or order.get("ShippingAddress")
            # Ở đây ta lấy từ record Odoo đã lưu.
            
            addr = order.partner_shipping_id.street or order.partner_id.street
            if not addr:
                continue

            # Gọi hàm mapping
            tag_ids = misa_utils.map_address_to_tag_ids(self.env, addr)
            
            # Update nếu có thay đổi (optional check) hoặc cứ write đè
            if tag_ids:
                # tag_ids trả về dạng [(6, 0, [ids])]
                # Kiểm tra xem tag hiện tại khác không để tránh log write không cần thiết?
                # Nhưng [(6,0..)] là replace all, nên cứ write là safe nhất cho logic "Resync".
                order.write({'tag_ids': tag_ids})
                count += 1
        
        # Return action notification
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Cập nhật hoàn tất"),
                'message': _("Đã cập nhật Tag cho %s đơn hàng.") % count,
                'type': 'success',
                'sticky': False,
            }
        }
