from odoo import api, fields, models


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    stt = fields.Char(
        string="STT",
        compute="_compute_stt",
        store=False,
        help="Số thứ tự tự động của dòng sản phẩm trong đơn mua hàng",
    )
    production_year = fields.Char(
        string="Năm sản xuất",
        help="Năm sản xuất của sản phẩm",
    )
    country_of_origin = fields.Char(
        string="Xuất xứ",
        help="Quốc gia/Nơi xuất xứ của sản phẩm",
    )
    picking_ids = fields.Many2many(
        "stock.picking",
        compute="_compute_picking_info",
        string="Phiếu nhập kho",
        help="Các phiếu nhập kho liên kết với dòng sản phẩm này.",
    )
    picking_count = fields.Integer(
        compute="_compute_picking_info",
        string="Số lượng phiếu nhập",
    )

    @api.depends("move_ids", "move_ids.picking_id", "move_ids.state")
    def _compute_picking_info(self):
        for line in self:
            moves = line.move_ids.filtered(lambda m: m.picking_id and m.state != "cancel")
            pickings = moves.mapped("picking_id")
            line.picking_ids = pickings
            line.picking_count = len(pickings)

    def action_open_picking(self):
        self.ensure_one()
        pickings = self.picking_ids
        if not pickings:
            pickings = self.order_id.picking_ids.filtered(lambda p: p.state != "cancel")
        action = self.env["ir.actions.act_window"]._for_xml_id("stock.action_picking_tree_all")
        if len(pickings) == 1:
            action["views"] = [(self.env.ref("stock.view_picking_form").id, "form")]
            action["res_id"] = pickings.id
        else:
            action["domain"] = [("id", "in", pickings.ids)]
        return action

    @api.depends("order_id.order_line", "order_id.order_line.sequence", "order_id.order_line.display_type")
    def _compute_stt(self):
        for line in self:
            line.stt = False

        for order in self.mapped("order_id"):
            number = 0
            for line in order.order_line:
                if line.display_type:
                    line.stt = False
                    continue
                number += 1
                line.stt = str(number)

    def _prepare_stock_moves(self, picking):
        res = super()._prepare_stock_moves(picking)
        for re in res:
            re["production_year"] = self.production_year
            re["country_of_origin"] = self.country_of_origin
        return res

