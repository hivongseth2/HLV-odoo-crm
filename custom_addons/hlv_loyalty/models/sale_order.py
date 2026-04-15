# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    loyalty_voucher_id = fields.Many2one(
        'loyalty.voucher', string='Voucher áp dụng',
        copy=False, readonly=True,
    )
    loyalty_voucher_code = fields.Char(
        string='Mã Voucher', copy=False,
        help='Nhập mã Voucher để áp dụng giảm giá',
    )

    def action_apply_loyalty_voucher(self):
        """Áp dụng mã Voucher vào đơn hàng."""
        self.ensure_one()
        code = (self.loyalty_voucher_code or '').strip().upper()
        if not code:
            raise UserError('Vui lòng nhập mã Voucher!')

        voucher = self.env['loyalty.voucher'].sudo().search([
            ('code', '=', code),
        ], limit=1)

        if not voucher:
            raise UserError(f'Mã Voucher "{code}" không tồn tại!')

        # Validate
        self._validate_voucher(voucher)

        # Tính giá trị giảm giá
        order_amount = self.amount_untaxed
        discount_amount = voucher.compute_discount_amount(order_amount)
        if discount_amount <= 0:
            raise UserError('Không tính được giá trị giảm giá cho Voucher này!')

        # Đảm bảo giảm giá không vượt quá giá trị đơn hàng
        discount_amount = min(discount_amount, order_amount)

        # Tìm hoặc tạo sản phẩm dịch vụ "Giảm giá Voucher"
        discount_product = self._get_voucher_discount_product()

        # Xóa dòng giảm giá cũ nếu có
        old_lines = self.order_line.filtered(
            lambda l: l.product_id == discount_product
        )
        if old_lines:
            old_lines.unlink()

        # Tạo dòng giảm giá
        self.env['sale.order.line'].create({
            'order_id': self.id,
            'product_id': discount_product.id,
            'name': f'Giảm giá Voucher [{voucher.code}]',
            'product_uom_qty': 1,
            'price_unit': -discount_amount,
            'tax_id': [(5, 0, 0)],  # Không thuế
        })

        self.loyalty_voucher_id = voucher.id
        self.loyalty_voucher_code = voucher.code

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thành công',
                'message': f'Áp dụng Voucher {voucher.code} giảm {discount_amount:,.0f} VNĐ!',
                'type': 'success',
                'sticky': False,
            },
        }

    def _validate_voucher(self, voucher):
        """Kiểm tra hợp lệ Voucher."""
        if voucher.state != 'active':
            state_labels = dict(voucher._fields['state'].selection)
            raise UserError(
                f'Voucher {voucher.code} đang ở trạng thái: {state_labels.get(voucher.state, voucher.state)}'
            )

        # Kiểm tra hết hạn
        if voucher.date_expiry and voucher.date_expiry < fields.Datetime.now():
            raise UserError(f'Voucher {voucher.code} đã hết hạn!')

        # Kiểm tra khách hàng sở hữu
        if voucher.partner_id != self.partner_id:
            raise UserError(
                f'Voucher {voucher.code} thuộc sở hữu của {voucher.partner_id.name}, '
                f'không phải khách hàng trên đơn hàng ({self.partner_id.name})!'
            )

        # Kiểm tra giá trị đơn hàng tối thiểu
        if voucher.min_order_amount > 0 and self.amount_untaxed < voucher.min_order_amount:
            raise UserError(
                f'Đơn hàng cần đạt tối thiểu {voucher.min_order_amount:,.0f} VNĐ '
                f'để sử dụng Voucher này!'
            )

        # Kiểm tra danh mục sản phẩm (nếu áp dụng theo danh mục)
        if voucher.apply_on == 'category' and voucher.product_category_ids:
            allowed_categ_ids = voucher.product_category_ids.ids
            order_categ_ids = self.order_line.mapped('product_id.categ_id').ids
            if not set(order_categ_ids) & set(allowed_categ_ids):
                raise UserError(
                    'Đơn hàng không chứa sản phẩm thuộc danh mục áp dụng của Voucher này!'
                )

    def action_remove_loyalty_voucher(self):
        """Xóa Voucher đã áp dụng khỏi đơn hàng."""
        self.ensure_one()
        discount_product = self._get_voucher_discount_product()
        old_lines = self.order_line.filtered(
            lambda l: l.product_id == discount_product
        )
        if old_lines:
            old_lines.unlink()
        self.loyalty_voucher_id = False
        self.loyalty_voucher_code = False

    def action_confirm(self):
        """Override: Đánh dấu Voucher đã sử dụng khi xác nhận đơn hàng."""
        res = super().action_confirm()
        for order in self:
            if order.loyalty_voucher_id and order.loyalty_voucher_id.state == 'active':
                order.loyalty_voucher_id.sudo().write({
                    'state': 'used',
                    'used_sale_order_id': order.id,
                    'used_date': fields.Datetime.now(),
                    'used_company_id': order.company_id.id,
                })
        return res

    @api.model
    def _get_voucher_discount_product(self):
        """Lấy hoặc tạo sản phẩm dịch vụ 'Giảm giá Voucher'."""
        product = self.env.ref('hlv_loyalty.product_voucher_discount', raise_if_not_found=False)
        if not product:
            product = self.env['product.product'].sudo().search([
                ('default_code', '=', 'LOYALTY_VOUCHER_DISCOUNT'),
            ], limit=1)
        if not product:
            product = self.env['product.product'].sudo().create({
                'name': 'Giảm giá Voucher Loyalty',
                'default_code': 'LOYALTY_VOUCHER_DISCOUNT',
                'type': 'service',
                'list_price': 0,
                'sale_ok': True,
                'purchase_ok': False,
                'taxes_id': [(5, 0, 0)],
            })
        return product
