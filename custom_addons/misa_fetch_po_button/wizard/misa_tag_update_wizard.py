from odoo import models, fields, api, _

class MisaTagUpdateWizard(models.TransientModel):
    _name = 'misa.tag.update.wizard'
    _description = 'Wizard cập nhật Tag từ địa chỉ'

    from_date = fields.Date(string="Từ ngày", required=True, default=fields.Date.context_today)
    to_date = fields.Date(string="Đến ngày", required=True, default=fields.Date.context_today)
    skip_if_tagged = fields.Boolean(string="Bỏ qua đơn đã có thẻ", default=True, help="Nếu chọn, sẽ không cập nhật lại các đơn hàng đã có thẻ.")

    def action_update_tags(self):
        self.ensure_one()
        orders = self.env['sale.order'].search([
            ('date_order', '>=', self.from_date),
            ('date_order', '<=', self.to_date),
            ('state', '!=', 'cancel'), 
        ])

        count = 0
        misa_utils = self.env['misa.api.utils']
        
        for order in orders:
            if self.skip_if_tagged and order.tag_ids:
                continue

            addr = order.partner_shipping_id.street or order.partner_id.street
            if not addr:
                continue

            tag_ids = misa_utils.map_address_to_tag_ids(self.env, addr, htgh_str=order.x_studio_htgh)
            
            if tag_ids:
                order.write({'tag_ids': tag_ids})
                count += 1
        
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
