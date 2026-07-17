from odoo import _, fields, models
from odoo.exceptions import ValidationError


class StockMove(models.Model):
    _inherit = "stock.move"

    origin_country_id = fields.Many2one(
        comodel_name="res.country",
        string="Xuất xứ",
        related="purchase_line_id.origin_country_id",
        store=True,
        index=True,
    )

    def _action_done(self, cancel_backorder=False):
        moves_with_origin = self.filtered(
            lambda move: move.origin_country_id
            and move.picking_code == "incoming"
            and move.state not in ("done", "cancel")
        )

        result = super()._action_done(cancel_backorder=cancel_backorder)

        for move in moves_with_origin.filtered(lambda item: item.state == "done"):
            move_lines = move.move_line_ids.filtered(
                lambda line: line.quantity > 0 and line.lot_id
            )
            if not move_lines:
                raise ValidationError(
                    _(
                        "Không thể lưu xuất xứ %(origin)s cho sản phẩm %(product)s "
                        "vì dòng nhập kho chưa có lô/số sê-ri.",
                        origin=move.origin_country_id.display_name,
                        product=move.product_id.display_name,
                    )
                )

            lots = move_lines.mapped("lot_id")
            conflicting_lots = lots.filtered(
                lambda lot: lot.origin_country_id
                and lot.origin_country_id != move.origin_country_id
            )
            if conflicting_lots:
                raise ValidationError(
                    _(
                        "Lô/số sê-ri %(lots)s đã có xuất xứ khác với xuất xứ "
                        "%(origin)s trên đơn mua.",
                        lots=", ".join(conflicting_lots.mapped("name")),
                        origin=move.origin_country_id.display_name,
                    )
                )

            lots.filtered(lambda lot: not lot.origin_country_id).write(
                {"origin_country_id": move.origin_country_id.id}
            )

        return result
