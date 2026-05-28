# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging
from markupsafe import Markup

_logger = logging.getLogger(__name__)

class TransitService(models.AbstractModel):
    _name = 'hlv.barcode.transit.service'
    _description = 'Service for 2-step Inter-Warehouse Transit'

    def process_second_transfer(self, source_picking):
        """
        Xử lý sinh phiếu Bước 2 (Transit -> Kho Đích) dựa trên Liên hệ của phiếu Bước 1.
        Được gọi từ button_validate của stock.picking.
        """
        source_picking.ensure_one()

        if not source_picking.partner_id:
            raise UserError(_("Bạn phải chọn Liên hệ (kho nhận) trước khi xác nhận phiếu chuyển nội bộ 2 bước."))

        # 1. Xác định kho đích dựa vào partner_id
        dest_warehouse = self.env['stock.warehouse'].search([
            ('partner_id', '=', source_picking.partner_id.id)
        ], limit=1)

        if not dest_warehouse:
            raise UserError(_("Không tìm thấy kho tương ứng với Liên hệ %s") % source_picking.partner_id.display_name)

        # 2. Lấy loại hoạt động nhận hàng của kho đích dựa trên cấu hình (reception_steps)
        # Thông thường: one_step (nhận trực tiếp), two_steps (input -> stock), three_steps
        reception_steps = dest_warehouse.reception_steps
        if reception_steps == 'one_step':
            # Nhận 1 bước: Dùng lệnh Chuyển hàng nội bộ (INT) theo yêu cầu hoặc Receipts tùy chuẩn,
            # Theo yêu cầu khách hàng: "KBC KHD 1 bước nên là chuyển hàng nội bộ" -> int_type_id
            picking_type = dest_warehouse.int_type_id
        else:
            # Nhận 2, 3 bước: "TSN nhận 2 bước nên là lưu kho" -> in_type_id
            picking_type = dest_warehouse.in_type_id

        if not picking_type:
            # Fallback nếu không cấu hình đúng
            ops = self.env["stock.picking.type"].search([
                ("warehouse_id", "=", dest_warehouse.id),
                ("code", "in", ["incoming", "internal"])
            ])
            picking_type = ops.filtered(lambda r: r.code == 'incoming')[:1] or ops[:1]

        if not picking_type:
            raise UserError(_("Không tìm thấy loại hoạt động phù hợp (INT/IN) cho kho %s") % dest_warehouse.name)

        if not picking_type.default_location_dest_id:
            raise UserError(_("Loại hoạt động '%s' chưa có Vị trí đích mặc định.") % picking_type.display_name)

        final_dest_location_id = picking_type.default_location_dest_id
        transit_location = source_picking.location_dest_id

        _logger.info("Transit Service: Tạo phiếu Bước 2 từ %s đến %s, dùng picking_type: %s", 
                     transit_location.display_name, final_dest_location_id.display_name, picking_type.display_name)

        # 3. Tạo phiếu Bước 2
        # Cần bảo vệ default_location_src_id để Odoo không tự set lại.
        # Hoặc tạo phiếu với context bypass onchange.
        new_picking_vals = {
            "picking_type_id": picking_type.id,
            "location_id": transit_location.id,
            "location_dest_id": final_dest_location_id.id,
            "move_ids_without_package": [],
            "source_transfer_id": source_picking.id,
            "partner_id": source_picking.partner_id.id,
        }

        new_picking = self.env["stock.picking"].with_context(
            default_location_id=transit_location.id,
            default_location_dest_id=final_dest_location_id.id
        ).create(new_picking_vals)

        # Cưỡng ép lại location bằng SQL để an toàn trước onchange (giống deltatech)
        self.env.cr.execute("""
            UPDATE stock_picking SET location_id = %s WHERE id = %s
        """, (transit_location.id, new_picking.id))
        new_picking.invalidate_recordset(['location_id'])

        # 4. Sao chép các move và move_line
        self._copy_moves_and_lines(source_picking, new_picking)

        # 5. Xác nhận phiếu
        new_picking.action_confirm()

        # Đánh dấu đã tạo
        source_picking.write({'second_transfer_created': True})
        new_picking.write({'second_transfer_created': True})

        # 6. Ghi log chatter
        self._post_transit_messages(source_picking, new_picking, transit_location, final_dest_location_id)

        return new_picking

    def _copy_moves_and_lines(self, source_picking, new_picking):
        for move in source_picking.move_ids:
            new_move = move.copy({
                "picking_id": new_picking.id,
                "location_id": new_picking.location_id.id,
                "location_dest_id": new_picking.location_dest_id.id,
                "state": "draft",
                "move_line_ids": [],
            })

            # Copy move lines có quantity > 0
            for line in move.move_line_ids.filtered(lambda l: l.quantity > 0):
                self.env["stock.move.line"].create({
                    "picking_id": new_picking.id,
                    "move_id": new_move.id,
                    "product_id": line.product_id.id,
                    "product_uom_id": line.product_uom_id.id,
                    "quantity": line.quantity,
                    "location_id": new_picking.location_id.id,
                    "location_dest_id": new_picking.location_dest_id.id,
                    "package_id": line.result_package_id.id if line.result_package_id else False,
                    "result_package_id": line.result_package_id.id if line.result_package_id else False,
                })

    def _post_transit_messages(self, source_picking, new_picking, transit_location, final_dest_location_id):
        origin_link = Markup('<a href="#" data-oe-model="stock.picking" data-oe-id="%d">%s</a>') % (
            source_picking.id, source_picking.name
        )
        new_link = Markup('<a href="#" data-oe-model="stock.picking" data-oe-id="%d">%s</a>') % (
            new_picking.id, new_picking.name
        )

        src_warehouse = source_picking.picking_type_id.warehouse_id.name or "N/A"
        dest_warehouse = new_picking.picking_type_id.warehouse_id.name or "N/A"

        # Note for New Picking
        new_picking_msg = Markup("""
            <div style="background: linear-gradient(135deg, #e8f5e9, #c8e6c9); border-left: 4px solid #4caf50; padding: 12px; border-radius: 8px; margin: 8px 0;">
                <div style="font-weight: bold; color: #2e7d32; font-size: 14px; margin-bottom: 8px;">
                    📦 Phiếu nhận hàng từ Kho trung gian
                </div>
                <div style="color: #333; font-size: 13px;">
                    <div>🔗 <b>Phiếu nguồn:</b> %s</div>
                    <div>🏢 <b>Từ kho:</b> %s</div>
                    <div>📍 <b>Vị trí nguồn:</b> %s</div>
                    <div>📍 <b>Vị trí đích:</b> %s</div>
                </div>
            </div>
        """) % (origin_link, src_warehouse, transit_location.display_name, final_dest_location_id.display_name)

        new_picking.message_post(
            body=new_picking_msg,
            message_type="notification",
            subtype_xmlid="mail.mt_note",
        )

        # Note for Source Picking
        picking_msg = Markup("""
            <div style="background: linear-gradient(135deg, #e3f2fd, #bbdefb); border-left: 4px solid #2196f3; padding: 12px; border-radius: 8px; margin: 8px 0;">
                <div style="font-weight: bold; color: #1565c0; font-size: 14px; margin-bottom: 8px;">
                    🚚 Chuyển kho 2 bước hoàn tất
                </div>
                <div style="color: #333; font-size: 13px;">
                    <div>📦 <b>Phiếu nhận đã tạo:</b> %s</div>
                    <div>🏢 <b>Kho nhận:</b> %s</div>
                    <div>📍 <b>Kho trung gian:</b> %s</div>
                </div>
            </div>
        """) % (new_link, dest_warehouse, transit_location.display_name)

        source_picking.message_post(
            body=picking_msg,
            message_type="notification",
            subtype_xmlid="mail.mt_note",
        )
