from odoo import Command, models

# Danh tính của chính move âm; chép product_uom từ move khác mà không quy đổi SL là sai số lượng.
NEGATIVE_MERGE_KEEP_OWN = {"product_id", "product_uom", "purchase_line_id"}


class StockMove(models.Model):
    _inherit = "stock.move"

    def _negative_merge_key_vals(self):
        """Giá trị khoá gộp của move này, để một move âm tạo sau mang đúng khoá và được trừ vào nó.

        Phải chép cả field compute sửa được: location_id / location_dest_id / product_uom của
        stock.move đều là compute store readonly=False, và kệ nhận chính là trường hay lệch nhất.
        Bỏ field related (vd. scrapped — ghi vào sẽ ghi xuyên sang stock.location) và field
        compute chỉ đọc, vì chúng tự tính lại từ các field đã chép.
        """
        self.ensure_one()
        fnames = (
            set(self._prepare_merge_moves_distinct_fields())
            - set(self._prepare_merge_negative_moves_excluded_distinct_fields())
            - NEGATIVE_MERGE_KEEP_OWN
        )
        vals = {}
        for fname in fnames:
            field = self._fields[fname]
            # readonly của field thường (date_deadline...) chỉ là cờ giao diện, vẫn phải chép.
            if field.related or not field.store or (field.compute and field.readonly) or field.type == "one2many":
                continue
            if field.type == "many2one":
                vals[fname] = self[fname].id
            elif field.type == "many2many":
                vals[fname] = [Command.set(self[fname].ids)]
            else:
                vals[fname] = self[fname]
        return vals
