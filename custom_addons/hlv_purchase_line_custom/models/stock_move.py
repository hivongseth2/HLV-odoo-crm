from odoo import Command, api, fields, models

# Danh tính của chính move âm; chép product_uom từ move khác mà không quy đổi SL là sai số lượng.
NEGATIVE_MERGE_KEEP_OWN = {"product_id", "product_uom", "purchase_line_id"}


class StockMove(models.Model):
    _inherit = "stock.move"

    stt = fields.Char(
        string="STT",
        compute="_compute_stt",
        store=False,
        help="Số thứ tự của dòng trong phiếu nhập kho / đơn mua",
    )
    misa_purchase_order_org_ref_detail_id = fields.Char(
        string="MISA org_ref_detail_id",
        related="purchase_line_id.misa_purchase_order_org_ref_detail_id",
        store=True,
        readonly=True,
        help="MISA org_ref_detail_id được liên kết từ dòng đơn mua hàng",
    )

    @api.depends("purchase_line_id.stt", "picking_id.move_ids")
    def _compute_stt(self):
        for move in self:
            if move.purchase_line_id and move.purchase_line_id.stt:
                move.stt = move.purchase_line_id.stt
            elif move.picking_id:
                idx = 0
                for m in move.picking_id.move_ids:
                    if m.display_type:
                        continue
                    idx += 1
                    if m == move:
                        move.stt = str(idx)
                        break
                else:
                    move.stt = False
            else:
                move.stt = False

    def _negative_merge_key_vals(self):
        """Giá trị khoá gộp của move này, để một move âm tạo sau mang đúng khoá và được trừ vào nó.

        Chỉ chép field thường: field compute/related (vd. scrapped) tự tính lại từ field đã chép,
        còn ghi thẳng vào related sẽ ghi xuyên sang bản ghi nguồn.
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
            if field.compute or field.type == "one2many":
                continue
            if field.type == "many2one":
                vals[fname] = self[fname].id
            elif field.type == "many2many":
                vals[fname] = [Command.set(self[fname].ids)]
            else:
                vals[fname] = self[fname]
        return vals
