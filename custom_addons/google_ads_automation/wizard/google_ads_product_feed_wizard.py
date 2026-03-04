from odoo import api, fields, models, _
from odoo.exceptions import UserError


class GoogleAdsProductFeedAddWizard(models.TransientModel):
    _name = 'google.ads.product.feed.add.wizard'
    _description = 'Wizard Thêm Sản Phẩm Vào Feed'

    feed_id = fields.Many2one(
        'google.ads.product.feed', string='Feed', required=True,
    )
    product_ids = fields.Many2many(
        'product.template', string='Sản Phẩm',
        help='Chọn các sản phẩm muốn thêm vào Feed',
    )
    filter_category_id = fields.Many2one(
        'product.category', string='Lọc Theo Danh Mục',
        help='Chỉ hiển thị sản phẩm thuộc danh mục này',
    )
    filter_in_stock = fields.Boolean(
        string='Chỉ SP Còn Hàng', default=True,
        help='Chỉ thêm sản phẩm có tồn kho > 0',
    )

    def action_add_products(self):
        """Thêm sản phẩm đã chọn vào Feed"""
        self.ensure_one()
        if not self.product_ids:
            raise UserError(_("Vui lòng chọn ít nhất 1 sản phẩm."))

        FeedLine = self.env['google.ads.product.feed.line']
        existing_products = self.feed_id.line_ids.mapped('product_id')
        added = 0

        for product in self.product_ids:
            if product in existing_products:
                continue  # Đã có trong feed → bỏ qua
            if self.filter_in_stock and product.qty_available <= 0:
                continue

            FeedLine.create({
                'feed_id': self.feed_id.id,
                'product_id': product.id,
            })
            added += 1

        self.feed_id.message_post(
            body=_("Đã thêm %s sản phẩm vào Feed (bỏ qua %s đã tồn tại).")
                 % (added, len(self.product_ids) - added)
        )

        return {'type': 'ir.actions.act_window_close'}

    def action_add_all_from_category(self):
        """Thêm tất cả SP từ danh mục đã chọn"""
        self.ensure_one()
        if not self.filter_category_id:
            raise UserError(_("Vui lòng chọn danh mục sản phẩm trước."))

        domain = [('categ_id', 'child_of', self.filter_category_id.id)]
        if self.filter_in_stock:
            domain.append(('qty_available', '>', 0))

        products = self.env['product.template'].search(domain)
        self.product_ids = products
        return self.action_add_products()
