# -*- coding: utf-8 -*-
from odoo import models, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model_create_multi
    def create(self, vals_list):
        # Tạo đối tác bình thường
        partners = super(ResPartner, self).create(vals_list)

        # Lấy context truyền từ hành động "Tạo NCC"
        pr_line_id = self.env.context.get('link_to_pr_line_id')
        pr_item_id = self.env.context.get('link_to_pr_wizard_item_id')

        # Nếu chỉ tạo 1 đối tác và có ID dòng PR cần liên kết
        if len(partners) == 1:
            if pr_line_id:
                line = self.env['purchase.request.line'].sudo().browse(pr_line_id)
                if line.exists():
                    # Dùng sudo() để ghi kể cả khi PR ở trạng thái chờ phê duyệt (readonly)
                    line.sudo().write({
                        'sale_proposed_supplier_id': partners.id,
                        'misa_new_supplier_json': False, # Xóa dữ liệu tạm để ẩn nút
                    })
            elif pr_item_id:
                item = self.env['purchase.request.line.make.purchase.order.item'].sudo().browse(pr_item_id)
                if item.exists():
                    item.sudo().write({
                        'sale_proposed_supplier_id': partners.id,
                        'misa_new_supplier_json': False,
                    })

        return partners
