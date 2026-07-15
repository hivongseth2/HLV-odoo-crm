# -*- coding: utf-8 -*-
from odoo import models, api, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_partner_source = fields.Selection([
        ('manual', 'Thủ công')
    ], string="Nguồn", tracking=True)

    @api.model
    def default_get(self, fields_list):
        res = super(ResPartner, self).default_get(fields_list)
        if 'x_partner_source' in fields_list:
            res['x_partner_source'] = 'manual'
        return res

    @api.model
    def name_create(self, name):
        partner_id, partner_name = super(ResPartner, self).name_create(name)
        partner = self.browse(partner_id)
        if not partner.x_partner_source:
            partner.write({'x_partner_source': 'manual'})
        return partner_id, partner_name

    @api.model_create_multi
    def create(self, vals_list):
        # Tạo đối tác bình thường
        partners = super(ResPartner, self).create(vals_list)

        # Lấy context truyền từ hành động "Tạo NCC"
        pr_line_id = self.env.context.get('link_to_pr_line_id')
        pr_item_id = self.env.context.get('link_to_pr_wizard_item_id')

        # Thêm tag "Nhà cung cấp" vào hlv_filter_tag_ids nếu được tạo từ PR hoặc Wizard
        if pr_line_id or pr_item_id:
            tag_supplier = self.env['hlv.contact.filter.tag'].sudo().search([('name', '=', 'Nhà cung cấp')], limit=1)
            if not tag_supplier:
                tag_supplier = self.env['hlv.contact.filter.tag'].sudo().create({'name': 'Nhà cung cấp'})
            for partner in partners:
                if 'hlv_filter_tag_ids' in partner._fields:
                    partner.sudo().write({
                        'hlv_filter_tag_ids': [fields.Command.link(tag_supplier.id)]
                    })

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
                        'supplier_id': partners.id,
                        'misa_new_supplier_json': False,
                    })

        return partners
