# -*- coding: utf-8 -*-
"""Một lần kiểm liên kết sản phẩm Shopee ↔ Odoo: tìm phân loại Shopee đang gắn với sản phẩm Odoo không
cùng hàng (vd Shopee bán 1 pin + 1 sạc mà Odoo gắn combo máy + pin + sạc).

Chạy nền bằng cron theo từng bước, mỗi bước commit: vài trăm liên kết là vài trăm lần gọi Shopee (mỗi
sản phẩm có phân loại cần thêm một lần get_model_list) cộng vài chục lần gọi Claude — không thể nằm trong
request của người bấm nút. Worker khởi động lại giữa chừng thì cron chạy tiếp từ hàng đợi còn lại.

Các bước: links (lấy liên kết shopee.item) → fetch (lấy chi tiết + phân loại Shopee từng lô 50 sản phẩm)
→ ai (Claude so thành phần từng cặp, shopee_product_check_ai.py) → done. Tự kiểm định kỳ:
shopee_product_check_auto.py.
"""

import json
import logging
import time
from collections import Counter
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.hlv_product_agent.services.claude_api_payload import MODEL_CHOICES
from odoo.addons.sale_shopee.utils import ShopeeRateLimitError

from ..services import shopee_product_api
from ..services.product_rules import ISSUES_WITHOUT_PAIR, model_key, shopee_units

_logger = logging.getLogger(__name__)

CRON_XMLID = "hlv_shopee_product_check.ir_cron_shopee_product_check"
# Một lượt cron làm việc trong ngần này giây (cộng lần gọi Claude đang dở) rồi trả worker, hẹn lượt sau
# NEXT_BATCH_MINUTES phút — các cron khác chen vào giữa, không phải chờ cả lần kiểm.
BATCH_SECONDS = 120
NEXT_BATCH_MINUTES = 1
# Map nhầm là xuất nhầm hàng cho khách Shopee và đẩy tồn sai lên listing: dùng model giỏi nhất.
DEFAULT_AI_MODEL = "claude-opus-5-5"

STATES = [
    ("draft", "Nháp"),
    ("running", "Đang kiểm"),
    ("done", "Xong"),
    ("failed", "Lỗi"),
]
STEPS = [
    ("links", "Lấy liên kết Odoo"),
    ("fetch", "Lấy chi tiết Shopee"),
    ("ai", "AI so thành phần từng cặp"),
    ("done", "Xong"),
]


class CheckFailed(Exception):
    """Không chạy tiếp được; thông điệp hiện trên lần kiểm."""


class HlvShopeeProductCheck(models.Model):
    _name = "hlv.shopee.product.check"
    _inherit = ["mail.thread"]
    _description = "Kiểm liên kết sản phẩm Shopee ↔ Odoo"
    _order = "id desc"

    name = fields.Char("Tên", required=True, default=lambda self: self._default_name())
    shop_ids = fields.Many2many(
        "shopee.shop", string="Shop", required=True,
        default=lambda self: self.env["shopee.shop"].search([]))
    link_ids = fields.Many2many(
        "shopee.item", string="Chỉ kiểm các liên kết",
        help="Mở từ danh sách Sản phẩm Shopee (Hành động → Kiểm map nhầm với AI): chỉ kiểm các liên kết đã "
             "chọn. Để trống: kiểm mọi liên kết của các shop đã chọn.")
    ai_model = fields.Selection(MODEL_CHOICES, string="Model AI", default=DEFAULT_AI_MODEL, required=True)
    is_auto = fields.Boolean("Tự kiểm định kỳ", readonly=True,
                             help="Lần kiểm do lịch tự kiểm tạo (Cài đặt → Bán hàng → Kiểm map nhầm Shopee).")

    state =fields.Selection(STATES, default="draft", required=True, tracking=True)
    step = fields.Selection(STEPS, readonly=True)
    item_queue = fields.Text(help="JSON [[shop_id, item_id], ...] — sản phẩm Shopee còn chờ lấy chi tiết.")
    fetch_total = fields.Integer(readonly=True)
    error = fields.Text("Lỗi", readonly=True)
    started_at = fields.Datetime("Bắt đầu", readonly=True)
    finished_at = fields.Datetime("Xong lúc", readonly=True)

    line_ids = fields.One2many("hlv.shopee.product.check.line", "check_id")
    line_count = fields.Integer(compute="_compute_counts")
    ok_count = fields.Integer(compute="_compute_counts")
    review_count = fields.Integer(compute="_compute_counts")
    mismatch_count = fields.Integer(compute="_compute_counts")
    stale_count = fields.Integer(compute="_compute_counts")
    pending_count = fields.Integer(compute="_compute_counts")
    progress = fields.Char("Tiến độ", compute="_compute_progress")

    def _default_name(self):
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        return _("Kiểm map Shopee %s", now.strftime("%d/%m/%Y %H:%M"))

    @api.depends("line_ids.result")
    def _compute_counts(self):
        for check in self:
            counts = Counter(check.line_ids.mapped("result"))
            check.line_count = len(check.line_ids)
            check.ok_count = counts["ok"] + counts["fixed"]
            check.review_count = counts["review"]
            check.mismatch_count = counts["mismatch"]
            check.stale_count = counts["stale"]
            check.pending_count = counts["pending"]

    @api.depends("state", "step", "item_queue", "fetch_total", "line_ids.ai_state")
    def _compute_progress(self):
        for check in self:
            if check.state != "running":
                check.progress = False
            elif check.step == "fetch":
                left = len(json.loads(check.item_queue or "[]"))
                check.progress = _("Đã lấy %(done)s/%(total)s sản phẩm Shopee",
                                   done=check.fetch_total - left, total=check.fetch_total)
            elif check.step == "ai":
                check.progress = _("AI còn %s cặp cần so",
                                   len(check.line_ids.filtered(lambda line: line.ai_state == "pending")))
            else:
                check.progress = dict(STEPS).get(check.step)

    # === Hành động === #

    def action_start(self):
        for check in self:
            if not check.shop_ids:
                raise UserError(_("Chọn ít nhất một shop Shopee."))
            problems = ["%s (id %s): %s" % (shop.name, shop.id, self._shop_problem(shop))
                        for shop in check.shop_ids if self._shop_problem(shop)]
            if problems:
                raise UserError(_("Không đọc được Shopee cho: %s. Bỏ các liên kết của shop này rồi kiểm lại.",
                                  "; ".join(problems)))
            check.line_ids.unlink()
            check.write({"state": "running", "step": "links", "error": False, "item_queue": False,
                         "fetch_total": 0, "started_at": fields.Datetime.now(), "finished_at": False})
        self._trigger_cron()
        return True

    def action_run_ai(self):
        """Chạy AI cho các cặp chưa có kết luận (lần trước lỗi API, hoặc vừa sửa liên kết) — không lấy lại Shopee."""
        for check in self:
            check._queue_ai(check.line_ids.filtered(lambda line: line.ai_state != "done"))
            if not check.line_ids.filtered(lambda line: line.ai_state == "pending"):
                raise UserError(_("Không còn cặp nào cần AI kiểm."))
            check.write({"state": "running", "step": "ai", "error": False})
        self._trigger_cron()
        return True

    def action_open_lines(self):
        """Mở các dòng của lần kiểm; ``context['result_filter']`` lọc sẵn theo kết luận."""
        self.ensure_one()
        context = {}
        result = self.env.context.get("result_filter")
        if result:
            context["search_default_result_%s" % result] = 1
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": "hlv.shopee.product.check.line",
            "view_mode": "list,form",
            "domain": [("check_id", "=", self.id)],
            "context": context,
        }

    @api.model
    def action_check_links(self, links):
        """Từ danh sách Sản phẩm Shopee: kiểm ngay các liên kết đang chọn, mở lần kiểm vừa tạo."""
        if not links:
            raise UserError(_("Chọn ít nhất một dòng Sản phẩm Shopee."))
        check = self.create({"shop_ids": [(6, 0, links.shop_id.ids)], "link_ids": [(6, 0, links.ids)]})
        check.action_start()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": check.id,
            "view_mode": "form",
        }

    @api.model
    def _shop_problem(self, shop):
        """Vì sao không gọi Shopee được cho shop này (chuỗi để báo người dùng), hoặc False nếu gọi được."""
        if shop.account_id.partner_key == "dummy":
            # sale_shopee/data/neutralize.sql thay khoá bằng "dummy" khi Odoo.sh tạo staging / bản sao:
            # gọi Shopee sẽ lỗi khó hiểu ở giữa chừng, báo ngay từ đầu cho rõ.
            return _("database đã bị neutralize (staging), chỉ kiểm được trên production")
        if not shop.active or not shop.access_token:
            # Shop đã lưu trữ thường không còn token (vd shop DEWALT cũ trùng shop_id với shop đang dùng):
            # sale_shopee sẽ đòi uỷ quyền lại giữa chừng.
            return _("shop đã lưu trữ hoặc chưa kết nối Shopee")
        return False

    def _trigger_cron(self, at=None):
        self.env.ref(CRON_XMLID).sudo()._trigger(at)

    # === Cron === #

    @api.model
    def _cron_process(self):
        """Một lượt: làm tiếp các lần kiểm đang chạy trong BATCH_SECONDS rồi trả worker.

        Còn việc thì hẹn lượt sau NEXT_BATCH_MINUTES phút chứ không báo _notify_progress: báo tiến độ là Odoo
        chạy liền tới 10 lượt trên cùng worker (~20-30 phút với lần kiểm cả shop), các cron khác (MISA, đơn
        Shopee...) phải xếp hàng chờ. Shopee bắt chờ thì không hẹn sớm — đợi lịch 5 phút của cron.
        """
        deadline = time.monotonic() + BATCH_SECONDS
        for check in self.search([("state", "=", "running")], order="id"):
            if time.monotonic() >= deadline:
                break
            if not check._process(deadline):
                return
        if self.search_count([("state", "=", "running")]):
            self._trigger_cron(fields.Datetime.now() + timedelta(minutes=NEXT_BATCH_MINUTES))

    def _process(self, deadline):
        """Chạy các bước của một lần kiểm tới khi xong hoặc hết giờ. Lỗi → ghi lên lần kiểm, không ném ra.

        Trả False khi Shopee giới hạn tần suất (lần kiểm vẫn "đang kiểm", chạy tiếp ở lịch sau), True còn lại.
        """
        self.ensure_one()
        try:
            while self.state == "running" and time.monotonic() < deadline:
                getattr(self, "_step_%s" % self.step)(deadline)
                self.env.cr.commit()
        except ShopeeRateLimitError:
            self.env.cr.rollback()
            _logger.info("SHOPEE_CHECK %s: Shopee giới hạn tần suất, chờ lượt sau", self.id)
            return False
        except CheckFailed as failure:
            self._fail(str(failure))
        except (UserError, ValidationError) as error:
            self._fail(_("Shopee báo lỗi: %s", error.args[0] if error.args else error))
        except Exception:  # noqa: BLE001 — lỗi lạ cũng phải hiện trên lần kiểm, không để "đang kiểm" mãi
            _logger.exception("SHOPEE_CHECK %s lỗi", self.id)
            self._fail(_("Lỗi hệ thống khi kiểm, xem log Odoo."))
        self.env.cr.commit()
        return True

    def _fail(self, message):
        self.env.cr.rollback()
        self.write({"state": "failed", "error": message})

    # === Các bước === #

    def _step_links(self, deadline):
        """Tạo một dòng cho mỗi liên kết shopee.item cần kiểm, đánh dấu SP tạm và liên kết trùng."""
        Item = self.env["shopee.item"]
        links = self.link_ids or Item.search([("shop_id", "in", self.shop_ids.ids)])
        # Đếm trùng trên toàn bộ liên kết của các shop đó, kể cả khi chỉ kiểm vài liên kết.
        all_links = Item.search([("shop_id", "in", links.shop_id.ids)])
        counts = Counter(_link_key(link) for link in all_links)
        placeholder = self.env.ref("sale_shopee.default_sale_product", raise_if_not_found=False)
        self.env["hlv.shopee.product.check.line"].create([{
            "check_id": self.id,
            "shop_id": link.shop_id.id,
            "link_id": link.id,
            "item_identifier": link.shopee_item_identifier,
            "model_identifier": link.shopee_model_identifier or "0",
            "product_id": link.product_id.id,
            "is_placeholder": bool(placeholder) and link.product_id == placeholder,
            "is_duplicate": counts[_link_key(link)] > 1,
        } for link in links])
        # Xếp theo shop để mỗi lô get_item_base_info chỉ thuộc một shop.
        queue = sorted({(link.shop_id.id, link.shopee_item_identifier) for link in links},
                       key=lambda pair: (pair[0], len(pair[1]), pair[1]))
        self.write({"item_queue": json.dumps(queue), "fetch_total": len(queue), "step": "fetch"})

    def _step_fetch(self, deadline):
        queue = json.loads(self.item_queue or "[]")
        while queue and time.monotonic() < deadline:
            shop_id = queue[0][0]
            chunk = [item_id for pair_shop, item_id in queue[:shopee_product_api.BASE_INFO_BATCH]
                     if pair_shop == shop_id]
            self._fetch_chunk(self.env["shopee.shop"].browse(shop_id), chunk)
            queue = queue[len(chunk):]
            self.item_queue = json.dumps(queue)
            self.env.cr.commit()
        if not queue:
            self._finish_fetch()

    def _fetch_chunk(self, shop, item_ids):
        """Lấy chi tiết một lô sản phẩm Shopee và điền vào các dòng liên kết tương ứng.

        Id không còn trên Shopee thì Shopee chỉ bỏ khỏi item_list, không báo lỗi cả lô (đã thử thật) —
        dòng đó thành "không còn trên Shopee". Lỗi API thật (token, quyền app) ném ra, dừng lần kiểm.
        """
        items = shopee_product_api.get_items_base_info(shop, item_ids)
        found = {str(item.get("item_id")): item for item in items}
        units, single = {}, {}
        for item in items:
            models_response = shopee_product_api.get_model_list(shop, item["item_id"]) if item.get("has_model") else None
            for unit in shopee_units(item, models_response):
                units[(unit["item_id"], model_key(unit["model_id"]))] = unit
                if not item.get("has_model"):
                    single[unit["item_id"]] = unit

        wanted = set(item_ids)
        for line in self.line_ids.filtered(lambda line: line.shop_id == shop and line.item_identifier in wanted):
            # Sản phẩm Shopee không (còn) phân loại: đơn về với model_id 0, sale_shopee chỉ dò liên kết theo
            # item_id — liên kết còn ghi id phân loại cũ vẫn là liên kết đang dùng, phải so như thường.
            unit = units.get((line.item_identifier, model_key(line.model_identifier))) or single.get(line.item_identifier)
            if unit:
                line.write({
                    "checked": True, "fetched": True, "model_found": True,
                    "shopee_name": unit["name"], "shopee_model_name": unit["model_name"], "shopee_sku": unit["sku"],
                    "shopee_description": unit["description"],
                    "shopee_status": unit["status"], "shopee_price": unit["price"], "shopee_stock": unit["stock"],
                })
                continue
            item = found.get(line.item_identifier) or {}
            line.write({"checked": True, "fetched": bool(item), "model_found": False,
                        "shopee_name": item.get("item_name") or False,
                        "shopee_status": item.get("item_status") or False})

    def _finish_fetch(self):
        """Hết hàng đợi: kết luận các liên kết Shopee không trả gì, xếp các cặp cần AI."""
        lines = self.line_ids
        lines.filtered(lambda line: not line.checked).write({"checked": True, "fetched": False})
        self._queue_ai(lines)
        self.step = "ai" if lines.filtered(lambda line: line.ai_state == "pending") else "done"

    def _queue_ai(self, lines):
        """Cặp nào cần AI: có cả hai bên để so. Cặp đã được kết luận ở lần kiểm trước mà không đổi gì
        (cùng tên, mô tả, thành phần, cùng sản phẩm Odoo) thì dùng lại kết luận, không hỏi lại."""
        pairs = lines.filtered(lambda line: line.product_id and line.issue not in ISSUES_WITHOUT_PAIR)
        (lines - pairs).write({"ai_state": "skipped"})
        fingerprints = {line: line.pair_fingerprint() for line in pairs}
        previous = {}
        for old in self.env["hlv.shopee.product.check.line"].search(
                [("fingerprint", "in", list(set(fingerprints.values()))), ("ai_state", "=", "done"),
                 ("check_id", "!=", self.id)], order="id desc"):
            previous.setdefault(old.fingerprint, old)
        for line, fingerprint in fingerprints.items():
            old = previous.get(fingerprint)
            if old:
                line.write({"fingerprint": fingerprint, "ai_state": "done", "ai_verdict": old.ai_verdict,
                            "ai_reason": old.ai_reason, "ai_shopee_contents": old.ai_shopee_contents,
                            "ai_odoo_contents": old.ai_odoo_contents})
            else:
                line.write({"fingerprint": fingerprint, "ai_state": "pending"})

    def _step_done(self, deadline):
        self.write({"state": "done", "finished_at": fields.Datetime.now(), "item_queue": False})
        self.message_post(body=_(
            "Kiểm xong %(total)s liên kết: %(mismatch)s map nhầm, %(review)s cần xem, %(ok)s đúng, "
            "%(stale)s liên kết cũ (hàng / phân loại đã xoá trên Shopee).",
            total=self.line_count, mismatch=self.mismatch_count, review=self.review_count, ok=self.ok_count,
            stale=self.stale_count))


def _link_key(link):
    """(shop, item, model) của một shopee.item — model "0" / rỗng coi như nhau."""
    return link.shop_id.id, link.shopee_item_identifier, model_key(link.shopee_model_identifier)
