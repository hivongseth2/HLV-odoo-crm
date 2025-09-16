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

    # vẫn giữ để không vỡ view cũ, nhưng logic không còn phụ thuộc vào field này
    create_second_transfer_automatically = fields.Boolean(
        string="Tự động tạo phiếu nhận (bước 2)",
        related="picking_type_id.auto_second_transfer",
        store=True,
    )

    def open_transfer_wizard(self):
        if self.second_transfer_created:
            raise UserError(_("Đã tạo phiếu bước 2 rồi."))
        return {
            "name": _("Tạo phiếu bước 2"),
            "type": "ir.actions.act_window",
            "res_model": "stock.picking.transfer.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_picking_id": self.id},
        }

    def create_second_transfer_wizard(self, final_dest_location_id, picking_type_id):
        """Tạo phiếu nhận (bước 2) và ghi chú 2 chiều có kèm liên kết."""
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
                self.second_transfer_created = True

                origin_link = Markup(
                    '<a href="#" data-oe-model="stock.picking" data-oe-id="%d">%s</a>'
                ) % (picking.id, picking.name)
                new_link = Markup(
                    '<a href="#" data-oe-model="stock.picking" data-oe-id="%d">%s</a>'
                ) % (new_picking.id, new_picking.name)

                new_picking.message_post(
                    body=Markup("Phiếu này được tạo từ %s.") % origin_link,
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                )
                new_picking.source_transfer_id = picking.id

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
        # Cho mọi internal transfer đều là quy trình qua transit (nếu chưa tạo bước 2)
        for record in self:
            record.is_transit_transfer = (
                record.picking_type_id.code == "internal" and not record.second_transfer_created
            )
            if record.is_transit_transfer:
                record.action_toggle_is_locked()

    def button_validate(self):
        for picking in self:
            # ✅ Luồng auto cho TẤT CẢ internal transfers (không phụ thuộc auto_second_transfer, không chặn origin)
            if picking.picking_type_id.code == "internal" and not picking.second_transfer_created:
                # Cần có đối tác để xác định kho đích
                if not picking.partner_id:
                    raise UserError(
                        _("Bạn phải chọn Liên hệ (kho nhận) trước khi xác nhận phiếu chuyển nội bộ 2 bước.")
                    )

                # Tìm kho đích qua partner
                warehouse = self.env["stock.warehouse"].search(
                    [("partner_id", "=", picking.partner_id.id)], limit=1
                )
                if not warehouse:
                    raise UserError(
                        _("Không tìm thấy kho tương ứng với Liên hệ %s") % picking.partner_id.name
                    )

                # Tìm loại hoạt động nội bộ của kho đích (ưu tiên loại 'reception', nếu không có thì lấy bất kỳ 'internal')
                ops = self.env["stock.picking.type"].search(
                    [("warehouse_id", "=", warehouse.id), ("code", "=", "internal")]
                )
                next_operation = ops.filtered(lambda r: r.two_step_transfer_use == "reception")[:1] or ops[:1]
                if not next_operation:
                    raise UserError(
                        _("Không tìm thấy loại hoạt động nội bộ cho kho %s") % warehouse.name
                    )

                if not next_operation.default_location_dest_id:
                    raise UserError(
                        _("Loại hoạt động '%s' chưa có Vị trí đích mặc định.") % next_operation.display_name
                    )

                picking.create_second_transfer_wizard(
                    next_operation.default_location_dest_id, next_operation
                )

            # Ràng buộc phiếu 2 chỉ chứa sản phẩm có trong phiếu nguồn
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
