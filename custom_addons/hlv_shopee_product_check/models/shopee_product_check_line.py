# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..services.match_payload import pair_fingerprint
from ..services.product_rules import ISSUES, RESULT_PENDING, RESULTS, VERDICTS, detect_issue, final_result

AI_STATES = [
    ("pending", "Chờ AI"),
    ("done", "AI đã kiểm"),
    ("skipped", "Không hỏi AI"),
]
# Thứ tự hiện trong danh sách: dòng cần người xử lý lên đầu.
RESULT_PRIORITY = ["mismatch", "review", "pending", "stale", "fixed", "ok"]
# Nhóm được ghi vào liên kết shopee.item (security/security.xml).
LINK_EDITOR_GROUP = "hlv_shopee_product_check.group_shopee_link_editor"


class HlvShopeeProductCheckLine(models.Model):
    """Một liên kết shopee.item (phân loại Shopee ↔ sản phẩm Odoo) trong một lần kiểm."""
    _name = "hlv.shopee.product.check.line"
    _description = "Dòng kiểm liên kết sản phẩm Shopee"
    _order = "check_id, result_sequence, shop_id, item_identifier, model_identifier, id"

    check_id = fields.Many2one("hlv.shopee.product.check", required=True, ondelete="cascade", index=True)
    shop_id = fields.Many2one("shopee.shop", string="Shop", required=True, ondelete="cascade")
    link_id = fields.Many2one("shopee.item", string="Liên kết Odoo", ondelete="set null")
    item_identifier = fields.Char("ID sản phẩm Shopee", required=True)
    model_identifier = fields.Char("ID phân loại Shopee", help="0 = sản phẩm không có phân loại.")
    shopee_url = fields.Char("Link Shopee", compute="_compute_shopee_url")

    product_id = fields.Many2one("product.product", string="Sản phẩm Odoo")
    odoo_code = fields.Char(related="product_id.default_code", string="Mã Odoo")

    checked = fields.Boolean("Đã tra Shopee")
    fetched = fields.Boolean("Có trên Shopee")
    model_found = fields.Boolean("Còn phân loại")
    shopee_name = fields.Char("Tên trên Shopee")
    shopee_model_name = fields.Char("Phân loại")
    shopee_sku = fields.Char("SKU Shopee")
    shopee_description = fields.Text("Mô tả Shopee")
    shopee_status = fields.Char("Trạng thái Shopee")
    shopee_price = fields.Float("Giá Shopee", digits=(16, 0))
    shopee_stock = fields.Integer("Tồn Shopee")
    is_placeholder = fields.Boolean("Gắn SP tạm")
    is_duplicate = fields.Boolean("Liên kết trùng")

    issue = fields.Selection(ISSUES, string="Lỗi liên kết", compute="_compute_issue", store=True)
    ai_state = fields.Selection(AI_STATES, default="skipped", required=True)
    ai_verdict = fields.Selection(VERDICTS, string="AI kết luận")
    ai_shopee_contents = fields.Char("Shopee gồm", help="Thành phần bên Shopee do AI dựng từ tên, phân loại, mô tả.")
    ai_odoo_contents = fields.Char("Odoo gồm", help="Thành phần bên Odoo do AI dựng từ thành phần combo / tên.")
    ai_reason = fields.Char("Lý do AI")
    fingerprint = fields.Char(index=True, help="Vân tay cặp đã gửi AI — lần kiểm sau gặp lại thì dùng lại kết luận.")
    result = fields.Selection(RESULTS, string="Kết luận", compute="_compute_result", store=True, index=True)
    result_sequence = fields.Integer(compute="_compute_result", store=True)

    fix_product_id = fields.Many2one(
        "product.product", string="Sửa thành",
        help="Chọn sản phẩm Odoo đúng rồi bấm Áp dụng: liên kết shopee.item được sửa sang sản phẩm này.")
    applied = fields.Boolean("Đã sửa", readonly=True)
    can_apply = fields.Boolean(compute="_compute_can_apply")

    @api.depends("shop_id.shop_identifier", "item_identifier")
    def _compute_shopee_url(self):
        for line in self:
            line.shopee_url = "https://shopee.vn/product/%s/%s" % (
                line.shop_id.shop_identifier, line.item_identifier) if line.item_identifier else False

    @api.depends("checked", "fetched", "shopee_status", "model_found", "is_placeholder", "is_duplicate")
    def _compute_issue(self):
        for line in self:
            # Chưa tra Shopee xong thì chưa kết luận: lúc đó dòng nào cũng trông như "không còn trên Shopee".
            line.issue = detect_issue(line.fetched, line.shopee_status, line.model_found, line.is_placeholder,
                                      line.is_duplicate) if line.checked else False

    @api.depends("issue", "ai_state", "ai_verdict", "applied")
    def _compute_result(self):
        for line in self:
            line.result = final_result(line.issue, line.ai_state, line.ai_verdict, line.applied) \
                if line.issue or line.applied else RESULT_PENDING
            line.result_sequence = RESULT_PRIORITY.index(line.result)

    @api.depends("applied", "fix_product_id", "link_id")
    def _compute_can_apply(self):
        for line in self:
            line.can_apply = bool(line.link_id and line.fix_product_id and line.fix_product_id != line.product_id)

    def pair(self):
        """Cặp gửi AI (đầu vào của match_payload.match_message): mọi thứ cho biết trong hộp mỗi bên có gì.

        Không gửi cân nặng (Shopee khai phồng để chọn vận chuyển) và mô tả bán Odoo (trống) — xem match_payload."""
        self.ensure_one()
        product = self.product_id.with_context(display_default_code=False)
        return {
            "row": self.id,
            "shopee": {
                "item_id": self.item_identifier,
                "name": self.shopee_name or "",
                "variation": self.shopee_model_name or "",
                "sku": self.shopee_sku or "",
                "description": self.shopee_description or "",
            },
            "odoo": {
                "product_id": product.id,
                "code": product.default_code or "",
                "name": product.display_name or "",
                "components": self._odoo_components(product),
            },
        }

    def _odoo_components(self, product):
        """Thành phần combo của sản phẩm Odoo: BoM kit, không có thì dòng Combo Item (combo_product).

        BoM kit trước vì kho xuất theo nó (combo_product chỉ lưu danh sách, không tự tách hàng khi giao);
        combo chưa chuyển bằng hlv_combo_to_bom thì Combo Item là nguồn duy nhất. AI phải thấy đúng cái kho
        sẽ xuất. Trả list ``{"qty", "code", "name"}``; hàng lẻ → [].
        """
        bom = self.env["mrp.bom"]._bom_find(product, bom_type="phantom")[product]
        if bom:
            parts = [(line.product_qty, line.product_id) for line in bom.bom_line_ids]
        else:
            template = product.product_tmpl_id
            parts = [(line.product_quantity, line.product_id) for line in template.combo_product_id] \
                if template.is_combo else []
        return [{
            "qty": qty,
            "code": part.default_code or "",
            "name": part.with_context(display_default_code=False).display_name,
        } for qty, part in parts]

    def pair_fingerprint(self):
        return pair_fingerprint(self.pair())

    def _check_link_editor(self):
        """Ẩn nút trên view chưa đủ: nút gọi được thẳng qua RPC, nên kiểm lại ở đây."""
        if not self.env.user.has_group(LINK_EDITOR_GROUP):
            raise AccessError(_("Cần quyền \"Sửa / xoá liên kết Shopee từ lần kiểm\" (Thiết lập → Người dùng) "
                                "để sửa hoặc xoá liên kết Sản phẩm Shopee."))

    def action_apply_fix(self):
        """Sửa liên kết shopee.item sang sản phẩm ở cột "Sửa thành".

        Dòng chuyển về "chờ AI": bấm Chạy lại AI để AI kiểm luôn cặp mới, tránh sửa nhầm lần hai.
        """
        self._check_link_editor()
        lines = self.filtered("can_apply")
        if not lines:
            raise UserError(_("Chọn sản phẩm đúng ở cột \"Sửa thành\" trước."))
        done = {}
        for line in lines:
            product = line.fix_product_id
            done.setdefault(line.check_id, []).append("%s → %s (trước: %s)" % (
                line.shopee_name or line.item_identifier, product.display_name, line.product_id.display_name))
            line.link_id.product_id = product
            line.write({"product_id": product.id, "fix_product_id": False, "is_placeholder": False,
                        "applied": True, "ai_state": "pending", "ai_verdict": False, "ai_reason": False,
                        "ai_shopee_contents": False, "ai_odoo_contents": False, "fingerprint": False})
        for check, pairs in done.items():
            check.message_post(body=_("Đã sửa %(count)s liên kết: %(pairs)s",
                                      count=len(pairs), pairs="; ".join(pairs)))
        return True

    def action_delete_stale_links(self):
        """Xoá liên kết shopee.item của các dòng "Liên kết cũ" (hàng / phân loại đã xoá trên Shopee).

        Không còn đơn nào về qua các liên kết này, nhưng đồng bộ tồn của sale_shopee vẫn gửi model_id chết
        lên Shopee cùng lô với các phân loại còn sống. Nếu Shopee đăng lại đúng phân loại đó, đơn đầu tiên
        sẽ tạo lại liên kết theo SKU như bình thường.
        """
        self._check_link_editor()
        lines = self.filtered(lambda line: line.result == "stale" and line.link_id)
        if not lines:
            raise UserError(_("Chọn các dòng \"Liên kết cũ\" còn liên kết để xoá."))
        for check, check_lines in lines.grouped("check_id").items():
            check.message_post(body=_("Đã xoá %(count)s liên kết cũ: %(links)s", count=len(check_lines), links="; ".join(
                "%s/%s → %s" % (line.item_identifier, line.model_identifier, line.product_id.display_name)
                for line in check_lines)))
        links = lines.link_id
        lines.write({"applied": True, "ai_state": "skipped"})
        links.unlink()
        return True
