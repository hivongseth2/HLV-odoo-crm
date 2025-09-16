# models/stock_picking.py

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from markupsafe import Markup

class StockPicking(models.Model):
    _inherit = "stock.picking"

    is_transit_transfer = fields.Boolean(default=False, compute="_compute_is_transit_transfer")
    sub_location_existent = fields.Boolean(default=False, compute="_compute_sub_location_existent")
    second_transfer_created = fields.Boolean(default=False)
    source_transfer_id = fields.Many2one("stock.picking")
    create_second_transfer_automatically = fields.Boolean(
        string="Tự động tạo phiếu nhận (bước 2)",
        related="picking_type_id.auto_second_transfer",
        store=True,
    )

    def open_transfer_wizard(self):
        if self.second_transfer_created:
            raise UserError(_("Đã tạo phiếu bước 2 rồi."))
        return {
            "name": "Tạo phiếu bước 2",
            "type": "ir.actions.act_window",
            "res_model": "stock.picking.transfer.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_picking_id": self.id},
        }

    def create_second_transfer_wizard(self, final_dest_location_id, picking_type_id):
        for picking in self:
            if picking.picking_type_id.code == "internal":
                new_picking_vals = {
                    "picking_type_id": picking_type_id.id,
                    "location_id": picking.location_dest_id.id,
                    "location_dest_id": final_dest_location_id.id,
                    "move_ids_without_package": [],
                }
                new_picking = self.env["stock.picking"].create(new_picking_vals)
                self.copy_move_lines(picking, new_picking)
                new_picking.action_confirm()
                # new_picking.action_assign()
                # new_picking.do_unreserve()
                self.second_transfer_created = True

                origin_link = Markup('<a href="#" data-oe-model="stock.picking" data-oe-id="%d">%s</a>') % (
                    picking.id, picking.name
                )
                new_link = Markup('<a href="#" data-oe-model="stock.picking" data-oe-id="%d">%s</a>') % (
                    new_picking.id, new_picking.name
                )


                # Ghi chú ở phiếu mới: “Phiếu này được tạo từ …(link)”
                new_picking.message_post(
                    body=Markup("Phiếu này được tạo từ %s.") % origin_link,
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                )
                new_picking.source_transfer_id = picking.id

                # Ghi chú ở phiếu nguồn: “Đã tạo phiếu …(link)”
                picking.message_post(
                    body=Markup("Đã tạo phiếu %s.") % new_link,
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                )


                # Đồng bộ Liên hệ giữa 2 phiếu theo kho
                picking.write({"partner_id": picking_type_id.warehouse_id.partner_id.id})
                new_picking.write({"partner_id": picking.picking_type_id.warehouse_id.partner_id.id})
                return new_picking

    def copy_move_lines(self, source_picking, target_picking):
        for move in source_picking.move_ids_without_package:
            move.copy(
                {
                    "picking_id": target_picking.id,
                    "location_id": source_picking.location_dest_id.id,
                    "location_dest_id": target_picking.location_dest_id.id,
                    "state": "draft",
                }
            )

    # @api.model
    # def create(self, vals):
    #     res = super().create(vals)
    #     if res.picking_type_id.code == "internal" and res.picking_type_id.next_operation_id:
    #         res.action_toggle_is_locked()
    #        # res.immediate_transfer = False
    #     return res

    def _compute_sub_location_existent(self):
        for record in self:
            sub_location_usage = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param(key="deltatech_picking_transit.use_sub_locations", default=False)
            )
            if sub_location_usage and self.picking_type_id.code == "internal":
                record.sub_location_existent = True
            else:
                record.sub_location_existent = False

    def reassign_location(self):
        for move_line in self.move_line_ids:
            quants = self.env["stock.quant"].search(
                [
                    ("product_id", "=", move_line.product_id.id),
                    ("location_id", "child_of", self.location_id.id),
                    ("quantity", ">", 0.0),
                ]
            )
            if quants:
                move_line.location_id = quants[0].location_id

    @api.onchange("picking_type_id")
    def _compute_is_transit_transfer(self):
        for record in self:
            if self.second_transfer_created:
                record.is_transit_transfer = False
                return
            if record.picking_type_id.code == "internal" and record.picking_type_id.two_step_transfer_use == "delivery":
                record.is_transit_transfer = True
                record.action_toggle_is_locked()
            # record.immediate_transfer = False
            else:
                record.is_transit_transfer = False

    def button_validate(self):
        for picking in self:
            # to make the module work automatically without the wizard will have some conditions, if the document was an origin it will not create the second transfer automatically because it assumes that the picking comes from a different document so it has the counter part created (eg: replenishment, sale order with replenishment form a different warehouse, etc))
            if (
                picking.create_second_transfer_automatically
                and not picking.second_transfer_created
                and not picking.origin
            ):
                if (
                    not picking.partner_id
                ):  # we use the partner to find the warehouse where the products need to arrive to
                    raise UserError(
                        _(
                            "Bạn phải chọn Liên hệ trước khi xác nhận phiếu khi sử dụng 2 bước và bật tự động tạo phiếu nhận."

                        
                        )
                    )
                warehouse = self.env["stock.warehouse"].search([("partner_id", "=", picking.partner_id.id)], limit=1)
                if warehouse:
                    next_operation = self.env["stock.picking.type"].search(
                        [
                            ("warehouse_id", "=", warehouse.id),
                            ("code", "=", "internal"),
                            ("two_step_transfer_use", "=", "reception"),
                        ],
                        limit=1,
                    )
                    if next_operation:
                        picking.create_second_transfer_wizard(next_operation.default_location_dest_id, next_operation)
                    else:
                        raise UserError(_("Không tìm thấy loại hoạt động 2 bước (Reception) cho kho %s") % warehouse.name)
                else:
                    raise UserError(_("Không tìm thấy kho tương ứng với Liên hệ %s") % picking.partner_id.name)
            if picking.source_transfer_id:
                for move in picking.move_ids_without_package:
                    other_moves = picking.source_transfer_id.move_ids_without_package.filtered(
                        lambda x: x.product_id == move.product_id
                    )
                    if not other_moves:
                        raise UserError(
                            _("Không thể xác nhận phiếu vì sản phẩm %s không có trong phiếu nguồn.")
                            % move.product_id.display_name
                        )
        return super().button_validate()
