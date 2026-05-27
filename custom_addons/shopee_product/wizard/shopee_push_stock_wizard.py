# -*- coding: utf-8 -*-
"""
wizard/shopee_push_stock_wizard.py

Wizard nhập tồn kho mới cho sản phẩm Shopee KHÔNG có biến thể.
Với sản phẩm có biến thể, dùng trực tiếp field new_stock trên model_ids.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services import shopee_product_api

_logger = logging.getLogger(__name__)


class ShopeePushStockWizard(models.TransientModel):
    _name = 'shopee.push.stock.wizard'
    _description = 'Cập nhật tồn kho Shopee (không biến thể)'

    shopee_product_id = fields.Many2one(
        'shopee.product',
        string='Sản phẩm',
        required=True,
        readonly=True,
    )
    current_stock = fields.Integer(
        string='Tồn kho hiện tại',
        compute='_compute_current',
    )
    new_stock = fields.Integer(
        string='Tồn kho mới',
        required=True,
    )

    @api.depends('shopee_product_id')
    def _compute_current(self):
        for rec in self:
            rec.current_stock = rec.shopee_product_id.total_available_stock

    @api.onchange('shopee_product_id')
    def _onchange_product(self):
        if self.shopee_product_id:
            self.new_stock = self.shopee_product_id.total_available_stock

    def action_confirm(self):
        self.ensure_one()
        product = self.shopee_product_id
        from odoo.addons.shopee_order_fetch.services.shopee_api import (
            get_credentials_from_shop,
        )
        creds = get_credentials_from_shop(product.shop_id)

        stock_list = [
            {'model_id': 0, 'seller_stock': [{'stock': self.new_stock}]}
        ]
        success, failure = shopee_product_api.call_update_stock(
            creds, product.shopee_item_id, stock_list
        )

        if failure:
            msgs = ', '.join(
                f"{f.get('failed_reason')}" for f in failure
            )
            raise UserError(_('Cập nhật tồn kho thất bại: %s') % msgs)

        product.write({'total_available_stock': self.new_stock})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Thành công'),
                'message': _('Đã cập nhật tồn kho lên %d.') % self.new_stock,
                'type': 'success',
                'sticky': False,
            },
        }
