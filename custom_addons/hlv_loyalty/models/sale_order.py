# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    loyalty_voucher_id = fields.Many2one(
        'hlv.loyalty.voucher', string='Voucher áp dụng',
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

        voucher = self.env['hlv.loyalty.voucher'].sudo().search([
            ('code', '=', code),
        ], limit=1)

        if not voucher:
            raise UserError(f'Mã Voucher "{code}" không tồn tại!')

        # Validate
        self._validate_voucher(voucher)

        # Gỡ hiệu lực voucher cũ trước khi áp mới
        self._remove_loyalty_reward_lines()

        if voucher.reward_type == 'discount':
            self._apply_discount_voucher(voucher)
            message = f'Áp dụng Voucher {voucher.code} thành công (giảm giá)!'
        elif voucher.reward_type == 'free_shipping':
            self._apply_free_shipping_voucher(voucher)
            message = f'Áp dụng Voucher {voucher.code} thành công (miễn phí vận chuyển)!'
        elif voucher.reward_type == 'gift':
            self._apply_gift_voucher(voucher)
            message = f'Áp dụng Voucher {voucher.code} thành công (tặng quà)!'
        else:
            raise UserError('Loại chương trình voucher chưa được hỗ trợ!')

        self.loyalty_voucher_id = voucher.id
        self.loyalty_voucher_code = voucher.code

        return {
            'type': 'ir.actions.act_window',
            'name': 'Đơn bán hàng',
            'res_model': 'sale.order',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_loyalty_voucher_code': self.loyalty_voucher_code,
                'hlv_loyalty_message': message,
            },
        }

    def _apply_discount_voucher(self, voucher):
        self.ensure_one()
        order_amount = self.amount_untaxed
        discount_amount = voucher.compute_discount_amount(order_amount)
        if discount_amount <= 0:
            raise UserError('Không tính được giá trị giảm giá cho Voucher này!')

        # Đảm bảo giảm giá không vượt quá giá trị đơn hàng
        discount_amount = min(discount_amount, order_amount)
        discount_product = self._get_voucher_discount_product()

        self.env['sale.order.line'].create({
            'order_id': self.id,
            'product_id': discount_product.id,
            'name': f'Giảm giá Voucher [{voucher.code}]',
            'product_uom_qty': 1,
            'price_unit': -discount_amount,
            'tax_id': [(5, 0, 0)],
            'is_loyalty_reward_line': True,
            'loyalty_reward_voucher_id': voucher.id,
        })

    def _apply_free_shipping_voucher(self, voucher):
        self.ensure_one()
        delivery_lines = self._get_delivery_charge_lines().filtered(
            lambda l: l.price_unit > 0 and l.product_uom_qty > 0
        )
        if not delivery_lines:
            raise UserError('Đơn hàng chưa có phí vận chuyển để áp dụng voucher miễn phí vận chuyển!')

        shipping_discount_product = self._get_voucher_shipping_discount_product()
        for line in delivery_lines:
            self.env['sale.order.line'].create({
                'order_id': self.id,
                'product_id': shipping_discount_product.id,
                'name': f'Miễn phí vận chuyển Voucher [{voucher.code}] - {line.name}',
                'product_uom_qty': line.product_uom_qty,
                'price_unit': -line.price_unit,
                'discount': line.discount,
                'tax_id': [(6, 0, line.tax_id.ids)],
                'is_loyalty_reward_line': True,
                'loyalty_reward_voucher_id': voucher.id,
            })

    def _get_delivery_charge_lines(self):
        """Tìm dòng phí vận chuyển từ carrier product, is_delivery hoặc tên dòng giao hàng."""
        self.ensure_one()
        carrier_product = self.carrier_id.product_id if self.carrier_id else False
        carrier_product_ids = set(self.env['delivery.carrier'].sudo().search([]).mapped('product_id').ids)

        def _is_delivery_keyword_line(line):
            name = (line.name or '').lower()
            keywords = ('giao hàng', 'vận chuyển', 'shipping', 'delivery', 'phí ship', 'ship')
            return any(k in name for k in keywords)

        return self.order_line.filtered(
            lambda l: (
                not l.display_type
                and not l.is_loyalty_reward_line
                and (
                    bool(getattr(l, 'is_delivery', False))
                    or (carrier_product and l.product_id == carrier_product)
                    or (l.product_id and l.product_id.id in carrier_product_ids)
                    or _is_delivery_keyword_line(l)
                )
            )
        )

    def _apply_gift_voucher(self, voucher):
        self.ensure_one()
        if not voucher.gift_product_id:
            raise UserError('Voucher quà tặng chưa được cấu hình sản phẩm quà tặng!')

        self.env['sale.order.line'].create({
            'order_id': self.id,
            'product_id': voucher.gift_product_id.id,
            'name': f'Quà tặng từ Voucher [{voucher.code}]',
            'product_uom_qty': voucher.gift_qty or 1,
            'price_unit': 0,
            'tax_id': [(5, 0, 0)],
            'is_loyalty_reward_line': True,
            'loyalty_reward_voucher_id': voucher.id,
        })

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

        # Kiểm tra khách hàng sở hữu:
        # Cho phép nếu order partner là chính chủ voucher, hoặc là công ty con
        # (bất kỳ cấp) của chủ voucher (hỗ trợ cấu trúc đa công ty).
        def _is_descendant_or_self(partner, ancestor):
            """True nếu partner == ancestor hoặc ancestor là tổ tiên của partner."""
            p = partner
            while p:
                if p == ancestor:
                    return True
                p = p.parent_id
            return False

        if not _is_descendant_or_self(self.partner_id, voucher.partner_id):
            raise UserError(
                f'Voucher {voucher.code} thuộc sở hữu của {voucher.partner_id.name}, '
                f'không thể dùng cho khách hàng {self.partner_id.name}!'
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
        self._remove_loyalty_reward_lines()
        self.loyalty_voucher_id = False
        self.loyalty_voucher_code = False
        return {
            'type': 'ir.actions.act_window',
            'name': 'Đơn bán hàng',
            'res_model': 'sale.order',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _remove_loyalty_reward_lines(self):
        self.ensure_one()
        reward_lines = self.order_line.filtered(lambda l: l.is_loyalty_reward_line)
        if reward_lines:
            reward_lines.unlink()

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

    @api.model
    def _get_voucher_shipping_discount_product(self):
        """Lấy hoặc tạo sản phẩm dịch vụ cho dòng miễn phí vận chuyển voucher."""
        product = self.env['product.product'].sudo().search([
            ('default_code', '=', 'LOYALTY_FREE_SHIPPING_DISCOUNT'),
        ], limit=1)
        if not product:
            product = self.env['product.product'].sudo().create({
                'name': 'Miễn phí vận chuyển Voucher Loyalty',
                'default_code': 'LOYALTY_FREE_SHIPPING_DISCOUNT',
                'type': 'service',
                'list_price': 0,
                'sale_ok': True,
                'purchase_ok': False,
                'taxes_id': [(5, 0, 0)],
            })
        return product


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    is_loyalty_reward_line = fields.Boolean(
        string='Dòng thưởng Loyalty', default=False, copy=False,
    )
    loyalty_reward_voucher_id = fields.Many2one(
        'hlv.loyalty.voucher', string='Voucher thưởng', copy=False,
    )
    loyalty_discount_pct = fields.Float(
        string='CK Loyalty (%)',
        default=0.0,
        digits=(5, 2),
        help='% chiết khấu dùng để tính điểm Loyalty cho dòng hàng này. Không ảnh hưởng giá bán. VD: 5 = 5%.',
    )

    def _get_loyalty_discount_amount(self):
        """Tính thành tiền CK Loyalty trên toàn bộ số lượng đặt hàng.

        `loyalty_discount_pct` được nhập theo 1 trong 2 cách: số phần trăm
        (VD: 5 = 5%) hoặc tỷ lệ thập phân (VD: 0.05 = 5%). Giá trị <= 1.0
        được hiểu là tỷ lệ thập phân sẵn có; giá trị > 1.0 được hiểu là số
        phần trăm cần chia 100. Phải khớp với logic ở
        `stock.picking._get_loyalty_discount_detail_for_line()` vì đó là
        nơi fallback về % nếu field Studio này chưa có giá trị.
        """
        self.ensure_one()
        discount_pct = float(self.loyalty_discount_pct or 0.0)
        if discount_pct <= 0:
            return 0.0

        discount_rate = discount_pct if discount_pct <= 1.0 else discount_pct / 100.0
        amount = (
            float(self.price_unit or 0.0)
            * float(self.product_uom_qty or 0.0)
            * discount_rate
        )
        currency = self.currency_id
        return currency.round(amount) if currency else amount

    def _sync_loyalty_discount_amount(self):
        """Đồng bộ field Studio thành tiền từ % CK Loyalty."""
        if 'x_studio_loyalty_discount_amount' not in self._fields:
            return

        for line in self:
            amount = line._get_loyalty_discount_amount()
            current_amount = float(
                line.x_studio_loyalty_discount_amount or 0.0
            )
            if abs(current_amount - amount) >= 0.0001:
                super(SaleOrderLine, line).write({
                    'x_studio_loyalty_discount_amount': amount,
                })

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._sync_loyalty_discount_amount()
        return lines

    def write(self, vals):
        result = super().write(vals)
        if self._LOYALTY_AMOUNT_TRIGGER_FIELDS.intersection(vals):
            self._sync_loyalty_discount_amount()
        return result

    @api.onchange('loyalty_discount_pct', 'price_unit', 'product_uom_qty')
    def _onchange_loyalty_discount_amount(self):
        if 'x_studio_loyalty_discount_amount' not in self._fields:
            return
        for line in self:
            line.x_studio_loyalty_discount_amount = (
                line._get_loyalty_discount_amount()
            )
