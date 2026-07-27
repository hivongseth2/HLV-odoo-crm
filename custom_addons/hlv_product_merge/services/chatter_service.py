# -*- coding: utf-8 -*-

from markupsafe import Markup


class ProductMergeChatterMixin:
    def _message_target(self, product):
        return product if hasattr(product, "message_post") else product.product_tmpl_id

    def _post_chatter_logs(self, details):
        self.ensure_one()
        source = self.source_product_id.with_context(active_test=False)
        base = self.base_product_id
        source_link = Markup(
            '<a href="#" data-oe-model="product.product" data-oe-id="%s">%s</a>'
        ) % (source.id, source.display_name)
        base_link = Markup(
            '<a href="#" data-oe-model="product.product" data-oe-id="%s">%s</a>'
        ) % (base.id, base.display_name)

        detail_items = Markup("").join(
            Markup("<li>%s%s: %s %s → %s %s</li>") % (
                detail["location"],
                (" · " + detail["lot"]) if detail["lot"] else "",
                self._format_qty(detail["source_qty"]),
                self.source_uom_id.display_name,
                self._format_qty(detail["target_qty"]),
                self.base_uom_id.display_name,
            )
            for detail in details
        )
        note_html = Markup("<br/>Ghi chú: %s") % self.note if self.note else Markup("")
        base_body = Markup(
            "Đã gộp sản phẩm %s vào sản phẩm này.<br/>"
            "Người thực hiện: %s.%s"
        ) % (source_link, self.env.user.display_name, note_html)
        if detail_items:
            base_body += Markup("<br/>Tồn kho đã chuyển:<ul>%s</ul>") % detail_items
        self._message_target(base).message_post(
            body=base_body,
            subtype_xmlid="mail.mt_note",
        )

        source_body = Markup(
            "Sản phẩm này đã được gộp vào %s và đã được lưu trữ.<br/>"
            "Người thực hiện: %s.%s"
        ) % (base_link, self.env.user.display_name, note_html)
        self._message_target(source).message_post(
            body=source_body,
            subtype_xmlid="mail.mt_note",
        )
