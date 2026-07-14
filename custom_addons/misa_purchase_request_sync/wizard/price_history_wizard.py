# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PriceHistoryWizard(models.TransientModel):
    _name = 'price.history.wizard'
    _description = 'Chọn giá từ lịch sử mua hàng'

    line_id = fields.Many2one(
        'purchase.request.line',
        string="Dòng PR",
        required=True,
        readonly=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string="Sản phẩm",
        related='line_id.product_id',
        readonly=True,
    )
    supplierinfo_ids = fields.One2many(
        'price.history.wizard.line',
        'wizard_id',
        string="Lịch sử giá",
    )

    def action_load(self):
        """Load supplierinfo records vào wizard."""
        self.ensure_one()
        lines = []
        supplierinfos = self.env['product.supplierinfo'].search([
            ('product_tmpl_id', '=', self.product_id.product_tmpl_id.id)
        ], order='sequence, price')
        for si in supplierinfos:
            lines.append((0, 0, {
                'supplierinfo_id': si.id,
                'partner_id': si.partner_id.id,
                'price': si.price,
                'product_code': si.product_code or '',
                'min_qty': si.min_qty,
                'delay': si.delay,
            }))
        self.supplierinfo_ids = lines
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'price.history.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
            'context': self.env.context,
        }


class PriceHistoryWizardLine(models.TransientModel):
    _name = 'price.history.wizard.line'
    _description = 'Dòng lịch sử giá trong wizard'

    wizard_id = fields.Many2one(
        'price.history.wizard',
        string="Wizard",
        required=True,
        readonly=True,
        ondelete='cascade',
    )
    supplierinfo_id = fields.Many2one(
        'product.supplierinfo',
        string="Nguồn giá",
        readonly=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string="Nhà cung cấp",
        readonly=True,
    )
    price = fields.Float(
        string="Đơn giá",
        readonly=True,
    )
    product_code = fields.Char(
        string="Mã hàng NCC",
        readonly=True,
    )
    min_qty = fields.Float(
        string="SL tối thiểu",
        readonly=True,
    )
    delay = fields.Integer(
        string="Thời gian giao (ngày)",
        readonly=True,
    )

    def action_apply_price(self):
        """Áp dụng giá và NCC từ dòng này vào PR line."""
        self.ensure_one()
        self.wizard_id.line_id.write({
            'misa_price_before_tax': self.price,
            'misa_supplier_id': self.partner_id.id,
            'sale_proposed_supplier_id': self.partner_id.id,
        })
        
        # Ghi nhận giá trị vào Make Purchase Order Item tương ứng nếu có trong context
        item_id = self.env.context.get('active_make_order_item_id')
        if item_id:
            item = self.env['purchase.request.line.make.purchase.order.item'].sudo().browse(item_id)
            if item.exists():
                item.sudo().write({
                    'actual_price_unit': self.price,
                    'supplier_id': self.partner_id.id,
                })
        return {'type': 'ir.actions.act_window_close'}
