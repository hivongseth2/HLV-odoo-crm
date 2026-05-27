# -*- coding: utf-8 -*-
"""
wizard/shopee_product_sync_wizard.py

Wizard đồng bộ sản phẩm từ Shopee về Odoo.

Luồng:
  1. Chọn shop Shopee
  2. Chọn trạng thái item muốn sync (NORMAL, UNLIST, ...)
  3. Tuỳ chọn: lọc theo thời gian cập nhật
  4. Nhấn "Đồng bộ" → gọi get_item_list + get_item_base_info → upsert shopee.product
  5. Hiển thị kết quả (tạo mới / cập nhật)
"""
import logging
import time

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ShopeeProductSyncWizard(models.TransientModel):
    _name = 'shopee.product.sync.wizard'
    _description = 'Wizard Đồng Bộ Sản Phẩm Shopee'

    # ── Input ────────────────────────────────────────────
    shop_id = fields.Many2one(
        'shopee.shop',
        string='Cửa hàng Shopee',
        required=True,
    )

    sync_normal = fields.Boolean(string='Đang bán (NORMAL)', default=True)
    sync_unlist = fields.Boolean(string='Đang ẩn (UNLIST)', default=False)
    sync_banned = fields.Boolean(string='Bị cấm (BANNED)', default=False)
    sync_reviewing = fields.Boolean(string='Đang duyệt (REVIEWING)', default=False)

    filter_by_update_time = fields.Boolean(
        string='Lọc theo thời gian cập nhật',
        default=False,
        help='Chỉ đồng bộ các sản phẩm được Shopee cập nhật trong khoảng thời gian này.',
    )
    update_time_from = fields.Datetime(string='Từ ngày')
    update_time_to = fields.Datetime(string='Đến ngày')

    # ── Output (readonly, hiển thị sau khi sync) ─────────
    state = fields.Selection(
        [('draft', 'Chờ'), ('done', 'Hoàn thành'), ('error', 'Lỗi')],
        default='draft',
        string='Trạng thái',
    )
    result_created = fields.Integer(string='Tạo mới', readonly=True)
    result_updated = fields.Integer(string='Cập nhật', readonly=True)
    result_message = fields.Text(string='Kết quả', readonly=True)

    # ── Constraints ──────────────────────────────────────

    @api.constrains('filter_by_update_time', 'update_time_from', 'update_time_to')
    def _check_time_range(self):
        for rec in self:
            if rec.filter_by_update_time:
                if rec.update_time_from and rec.update_time_to:
                    if rec.update_time_from >= rec.update_time_to:
                        raise UserError(_("'Từ ngày' phải nhỏ hơn 'Đến ngày'."))

    # ── Action ───────────────────────────────────────────

    def action_sync(self):
        """Thực hiện đồng bộ và cập nhật kết quả."""
        self.ensure_one()

        statuses = []
        if self.sync_normal:
            statuses.append('NORMAL')
        if self.sync_unlist:
            statuses.append('UNLIST')
        if self.sync_banned:
            statuses.append('BANNED')
        if self.sync_reviewing:
            statuses.append('REVIEWING')

        if not statuses:
            raise UserError(_("Vui lòng chọn ít nhất một trạng thái sản phẩm để đồng bộ."))

        update_time_from = None
        update_time_to = None
        if self.filter_by_update_time:
            if self.update_time_from:
                update_time_from = int(
                    fields.Datetime.from_string(str(self.update_time_from)).timestamp()
                )
            if self.update_time_to:
                update_time_to = int(
                    fields.Datetime.from_string(str(self.update_time_to)).timestamp()
                )

        try:
            created, updated = self.env['shopee.product'].sync_from_shop(
                shop=self.shop_id,
                item_status=statuses,
                update_time_from=update_time_from,
                update_time_to=update_time_to,
            )
            self.write({
                'state': 'done',
                'result_created': created,
                'result_updated': updated,
                'result_message': (
                    f"Đồng bộ thành công!\n"
                    f"• Tạo mới: {created} sản phẩm\n"
                    f"• Cập nhật: {updated} sản phẩm\n"
                    f"• Tổng: {created + updated} sản phẩm"
                ),
            })
        except UserError:
            raise
        except Exception as e:
            self.write({
                'state': 'error',
                'result_message': f"Lỗi không xác định:\n{str(e)}",
            })
            _logger.exception("ShopeeProductSyncWizard: lỗi khi sync shop %s", self.shop_id.display_name)
            raise UserError(_("Đồng bộ thất bại:\n%s") % str(e))

        # Giữ wizard mở để xem kết quả
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_open_products(self):
        """Mở danh sách shopee.product của shop vừa sync."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sản phẩm Shopee — %s') % self.shop_id.display_name,
            'res_model': 'shopee.product',
            'view_mode': 'list,form',
            'domain': [('shop_id', '=', self.shop_id.id)],
            'context': {'default_shop_id': self.shop_id.id},
        }
