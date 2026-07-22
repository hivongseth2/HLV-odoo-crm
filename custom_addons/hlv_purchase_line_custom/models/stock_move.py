from odoo import api, fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    stt = fields.Char(
        string="STT",
        compute="_compute_stt",
        store=False,
        help="Số thứ tự của dòng trong phiếu nhập kho / đơn mua",
    )
    production_year = fields.Char(
        string="Năm sản xuất",
        related="purchase_line_id.production_year",
        store=True,
        readonly=False,
        help="Năm sản xuất được liên kết từ dòng đơn mua hàng",
    )
    country_of_origin = fields.Char(
        string="Xuất xứ",
        related="purchase_line_id.country_of_origin",
        store=True,
        readonly=False,
        help="Xuất xứ được liên kết từ dòng đơn mua hàng",
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
