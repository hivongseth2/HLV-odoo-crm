# -*- coding: utf-8 -*-
"""Tự kiểm map nhầm định kỳ (Cài đặt → Bán hàng → Kiểm map nhầm Shopee, bật / tắt được).

Cron chạy mỗi đêm nhưng chỉ tạo lần kiểm khi đã đủ số ngày đặt trong cài đặt kể từ lần tự kiểm trước:
đổi chu kỳ trong cài đặt là có hiệu lực ngay, không phải sửa lịch cron. Cặp không đổi gì so với lần
trước thì dùng lại kết luận AI (vân tay), nên mỗi lần định kỳ chỉ tốn tiền cho phần thay đổi.

Xong thì báo cho người có quyền sửa liên kết (group_shopee_link_editor) khi có dòng map nhầm, nêu riêng
số dòng MỚI so với lần tự kiểm trước — dòng cũ chưa ai sửa không làm loãng thông báo.
"""

import logging

from odoo import _, api, fields, models
from odoo.tools.misc import str2bool

from .shopee_product_check_line import LINK_EDITOR_GROUP

_logger = logging.getLogger(__name__)

PARAM_AUTO = "hlv_shopee_product_check.auto_enabled"
PARAM_INTERVAL = "hlv_shopee_product_check.auto_interval_days"
DEFAULT_INTERVAL_DAYS = 7


class HlvShopeeProductCheck(models.Model):
    _inherit = "hlv.shopee.product.check"

    @api.model
    def auto_config(self):
        """Cài đặt tự kiểm, đã chuẩn hoá: {"enabled": bool, "interval_days": int ≥ 1}."""
        get = self.env["ir.config_parameter"].sudo().get_param
        try:
            interval = int(get(PARAM_INTERVAL) or DEFAULT_INTERVAL_DAYS)
        except ValueError:
            interval = DEFAULT_INTERVAL_DAYS
        return {"enabled": str2bool(get(PARAM_AUTO) or "False", False), "interval_days": max(interval, 1)}

    @api.model
    def _cron_auto_check(self):
        """Mỗi đêm: đến hạn thì tạo lần kiểm mọi shop đang kết nối được và bắt đầu chạy."""
        config = self.auto_config()
        if not config["enabled"]:
            return
        # Lần kiểm tay đang chạy thì để hôm sau — hai lần kiểm cùng lúc gọi Shopee / Claude gấp đôi.
        if self.search_count([("state", "=", "running")]):
            return
        last = self.search([("is_auto", "=", True), ("started_at", "!=", False)], order="started_at desc", limit=1)
        if last and (fields.Date.today() - last.started_at.date()).days < config["interval_days"]:
            return
        shops = self.env["shopee.shop"].search([]).filtered(lambda shop: not self._shop_problem(shop))
        if not shops:
            _logger.info("SHOPEE_CHECK tự kiểm: không có shop nào gọi Shopee được (staging / chưa kết nối)")
            return
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        check = self.create({
            "name": _("Tự kiểm map Shopee %s", now.strftime("%d/%m/%Y")),
            "shop_ids": [(6, 0, shops.ids)],
            "is_auto": True,
        })
        check.action_start()

    def _step_done(self, deadline):
        super()._step_done(deadline)
        if self.is_auto:
            self._notify_auto_result()

    def _notify_auto_result(self):
        """Báo người có quyền sửa liên kết khi lần tự kiểm có dòng map nhầm; không có thì im lặng."""
        mismatches = self.line_ids.filtered(lambda line: line.result == "mismatch")
        if not mismatches:
            return
        previous = self.search([("is_auto", "=", True), ("state", "=", "done"), ("id", "!=", self.id)],
                               order="id desc", limit=1)
        known = set(previous.line_ids.filtered(lambda line: line.result == "mismatch").link_id.ids)
        new = mismatches.filtered(lambda line: line.link_id.id not in known)
        partners = self.env.ref(LINK_EDITOR_GROUP).users.partner_id
        self.message_post(
            body=_("Tự kiểm định kỳ: %(total)s liên kết map nhầm, trong đó %(new)s mới so với lần trước. "
                   "Mở lần kiểm này → nút \"Map nhầm\" để xem và sửa.", total=len(mismatches), new=len(new)),
            partner_ids=partners.ids,
            subtype_xmlid="mail.mt_comment",
        )
