# models/stock_picking.py
import logging
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from markupsafe import Markup

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    is_transit_transfer = fields.Boolean(default=False, compute="_compute_is_transit_transfer")
    sub_location_existent = fields.Boolean(default=False, compute="_compute_sub_location_existent")
    second_transfer_created = fields.Boolean(default=False)
    source_transfer_id = fields.Many2one("stock.picking")

    # giữ để không vỡ view cũ (không còn phụ thuộc)
    create_second_transfer_automatically = fields.Boolean(
        string="Tự động tạo phiếu nhận (bước 2)",
        related="picking_type_id.auto_second_transfer",
        store=True,
    )

    # ---------------- Override onchange để bảo vệ location_id ----------------
    @api.onchange('picking_type_id', 'partner_id')
    def _onchange_picking_type(self):
        """
        Override để ngăn Odoo ghi đè location_id khi phiếu là bước 2 của transit transfer.
        Odoo core sẽ set location_id = picking_type_id.default_location_src_id,
        nhưng với phiếu nhận từ transit, ta cần giữ nguồn là Transit location.
        """
        # Lưu lại location_id hiện tại
        saved_location_id = self.location_id
        
        # Kiểm tra nếu phiếu này là phiếu bước 2 hoặc nguồn là transit
        # Dùng _origin để lấy giá trị từ database (record đã lưu)
        preserve_location = False
        
        # Check source_transfer_id từ _origin (record đã lưu trong DB)
        if hasattr(self, '_origin') and self._origin:
            origin_source_transfer = self._origin.source_transfer_id
            if origin_source_transfer:
                preserve_location = True
                _logger.warning(f"ONCHANGE: Phiếu có source_transfer_id={origin_source_transfer.id}, sẽ bảo vệ location_id")
        
        # Hoặc check nếu location_id hiện tại là transit
        if saved_location_id and (saved_location_id.usage == 'transit' or self._is_inter_warehouse_transit(saved_location_id)):
            preserve_location = True
            _logger.warning(f"ONCHANGE: Location hiện tại là Transit ({saved_location_id.id}), sẽ bảo vệ")
        
        _logger.warning(f"ONCHANGE: preserve_location={preserve_location}, saved_location_id={saved_location_id.id if saved_location_id else None}")
        
        # Gọi super để Odoo xử lý normal logic
        result = super()._onchange_picking_type()
        
        # Khôi phục location_id nếu cần bảo vệ
        if preserve_location and saved_location_id:
            _logger.warning(f"ONCHANGE: Khôi phục location_id từ {self.location_id.id if self.location_id else None} về {saved_location_id.id}")
            self.location_id = saved_location_id
        
        return result

    # ---------------- Helper ----------------
    def _is_inter_warehouse_transit(self, location):
        """Chỉ nhận 'Physical Locations/Inter-warehouse transit'.
        Ưu tiên check theo complete_name; fallback usage='transit'.
        """
        if not location:
            return False
        name_ok = (location.complete_name or "").strip().lower().endswith("physical locations/inter-warehouse transit".lower()) \
                  or (location.complete_name or "").strip().lower() == "physical locations/inter-warehouse transit".lower()
        return name_ok or (location.usage == "transit" and "inter-warehouse transit" in (location.complete_name or "").lower())

    # -------------- Wizard mở tay --------------
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

    # -------------- Tạo phiếu 2 --------------
    def create_second_transfer_wizard(self, final_dest_location_id, picking_type_id):
        """Tạo phiếu nhận (bước 2) và ghi chú 2 chiều có kèm liên kết."""
        for picking in self:
            if picking.picking_type_id.code == "internal":
                # Lưu lại transit location (đích của phiếu 1 = nguồn của phiếu 2)
                transit_location = picking.location_dest_id
                
                _logger.warning("="*50)
                _logger.warning("TRANSIT TRANSFER DEBUG - BẮT ĐẦU TẠO PHIẾU 2")
                _logger.warning(f"Transit location ID: {transit_location.id}")
                _logger.warning(f"Transit location name: {transit_location.complete_name}")
                _logger.warning(f"Picking type ID: {picking_type_id.id}")
                _logger.warning(f"Picking type default_location_src_id BEFORE: {picking_type_id.default_location_src_id.id if picking_type_id.default_location_src_id else None}")
                
                # =========== FIX QUAN TRỌNG ===========
                # Lưu lại default_location_src_id gốc của picking_type
                original_src_location = picking_type_id.default_location_src_id
                
                # Tạm thời thay đổi default_location_src_id thành transit
                # Dùng sudo và SQL để bypass mọi restriction
                self.env.cr.execute("""
                    UPDATE stock_picking_type 
                    SET default_location_src_id = %s 
                    WHERE id = %s
                """, (transit_location.id, picking_type_id.id))
                picking_type_id.invalidate_recordset(['default_location_src_id'])
                
                # Tạo picking - bây giờ sẽ dùng transit làm nguồn mặc định
                new_picking_vals = {
                    "picking_type_id": picking_type_id.id,
                    "location_id": transit_location.id,
                    "location_dest_id": final_dest_location_id.id,
                    "move_ids_without_package": [],
                    "source_transfer_id": picking.id,  # Đánh dấu ngay từ đầu
                }
                
                new_picking = self.env["stock.picking"].create(new_picking_vals)
                _logger.warning(f"New picking ID: {new_picking.id}, Name: {new_picking.name}")
                _logger.warning(f"New picking location_id AFTER CREATE: {new_picking.location_id.id} - {new_picking.location_id.complete_name}")
                
                # Copy move lines với location nguồn là transit
                self.copy_move_lines(picking, new_picking)
                
                # Confirm picking
                new_picking.action_confirm()
                _logger.warning(f"New picking location_id AFTER CONFIRM: {new_picking.location_id.id} - {new_picking.location_id.complete_name}")
                
                # Khôi phục default_location_src_id gốc
                self.env.cr.execute("""
                    UPDATE stock_picking_type 
                    SET default_location_src_id = %s 
                    WHERE id = %s
                """, (original_src_location.id if original_src_location else None, picking_type_id.id))
                picking_type_id.invalidate_recordset(['default_location_src_id'])
                
                # Đảm bảo chắc chắn location_id của picking là transit
                _logger.warning(f"EXECUTING SQL UPDATE với transit_location.id = {transit_location.id}")
                self.env.cr.execute("""
                    UPDATE stock_picking SET location_id = %s WHERE id = %s
                """, (transit_location.id, new_picking.id))
                self.env.cr.execute("""
                    UPDATE stock_move SET location_id = %s WHERE picking_id = %s
                """, (transit_location.id, new_picking.id))
                self.env.cr.execute("""
                    UPDATE stock_move_line SET location_id = %s WHERE picking_id = %s
                """, (transit_location.id, new_picking.id))
                
                new_picking.invalidate_recordset(['location_id'])
                new_picking.move_ids.invalidate_recordset(['location_id'])
                if new_picking.move_line_ids:
                    new_picking.move_line_ids.invalidate_recordset(['location_id'])
                
                _logger.warning(f"New picking location_id AFTER SQL UPDATE: {new_picking.location_id.id} - {new_picking.location_id.complete_name}")
                _logger.warning("TRANSIT TRANSFER DEBUG - KẾT THÚC")
                _logger.warning("="*50)
                # đánh dấu để tránh tự đẻ thêm
                new_picking.second_transfer_created = True
                self.second_transfer_created = True

                origin_link = Markup('<a href="#" data-oe-model="stock.picking" data-oe-id="%d">%s</a>') % (
                    picking.id, picking.name
                )
                new_link = Markup('<a href="#" data-oe-model="stock.picking" data-oe-id="%d">%s</a>') % (
                    new_picking.id, new_picking.name
                )

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

    @api.onchange("picking_type_id", "location_dest_id")
    def _compute_is_transit_transfer(self):
        """Chỉ bật cờ khi là internal và ĐÍCH là Inter-warehouse transit (phiếu 1)."""
        for record in self:
            record.is_transit_transfer = (
                record.picking_type_id.code == "internal"
                and not record.second_transfer_created
                and self._is_inter_warehouse_transit(record.location_dest_id)
            )
            if record.is_transit_transfer:
                record.action_toggle_is_locked()

    def button_validate(self):
        # Lưu thông tin để tạo phiếu bước 2 SAU khi đã validate và tách kiện
        pickings_need_second_transfer = []

        for picking in self:
            # Auto chỉ khi: Internal + chưa tạo lần nào + không phải phiếu con + ĐÍCH là transit
            if (
                picking.picking_type_id.code == "internal"
                and not picking.second_transfer_created
                and not picking.source_transfer_id
                and self._is_inter_warehouse_transit(picking.location_dest_id)
            ):
                # Bắt buộc có Liên hệ để xác định kho nhận
                if not picking.partner_id:
                    raise UserError(
                        _("Bạn phải chọn Liên hệ (kho nhận) trước khi xác nhận phiếu chuyển nội bộ 2 bước.")
                    )

                # Tìm kho đích qua partner
                warehouse = self.env["stock.warehouse"].search(
                    [("partner_id", "=", picking.partner_id.id)], limit=1
                )
                if not warehouse:
                    raise UserError(_("Không tìm thấy kho tương ứng với Liên hệ %s") % picking.partner_id.name)

                # Tìm loại hoạt động nội bộ của kho đích (ưu tiên 'reception'; nếu không có thì lấy bất kỳ 'internal')
                ops = self.env["stock.picking.type"].search(
                    [("warehouse_id", "=", warehouse.id), ("code", "=", "internal")]
                )
                next_operation = ops.filtered(lambda r: r.two_step_transfer_use == "reception")[:1] or ops[:1]
                if not next_operation:
                    raise UserError(_("Không tìm thấy loại hoạt động nội bộ cho kho %s") % warehouse.name)

                if not next_operation.default_location_dest_id:
                    raise UserError(_("Loại hoạt động '%s' chưa có Vị trí đích mặc định.") % next_operation.display_name)

                # Lưu thông tin để tạo SAU khi đã validate
                pickings_need_second_transfer.append({
                    'picking': picking,
                    'final_dest_location_id': next_operation.default_location_dest_id,
                    'next_operation': next_operation,
                })

            # Ràng buộc: phiếu 2 chỉ chứa SP có trong phiếu nguồn
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

        # Gọi validate gốc - nơi Odoo xử lý backorder/tách kiện
        result = super().button_validate()

        # SAU KHI đã validate và tách kiện (nếu có), mới tạo phiếu bước 2
        for info in pickings_need_second_transfer:
            picking = info['picking']
            # Chỉ tạo phiếu bước 2 cho phiếu đã validate (state = done)
            # Nếu có tách kiện, picking gốc là phiếu đã validate, backorder là phiếu chờ
            if picking.state == 'done':
                picking.create_second_transfer_wizard(
                    info['final_dest_location_id'],
                    info['next_operation']
                )

        return result
