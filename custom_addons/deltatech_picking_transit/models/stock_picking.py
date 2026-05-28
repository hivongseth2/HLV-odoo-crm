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
    second_transfer_created = fields.Boolean(default=False, copy=False)  # Không copy khi nhân bản
    source_transfer_id = fields.Many2one("stock.picking", copy=False)  # Không copy khi nhân bản

   
    create_second_transfer_automatically = fields.Boolean(
        string="Tự động tạo phiếu bước 2",
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

    # ---------------- Override write để bảo vệ location_id ----------------
    def write(self, vals):
        """
        Override write để ngăn việc ghi đè location_id khi phiếu là bước 2 của transit transfer.
        Nếu location_id bị thay đổi từ transit sang non-transit, sẽ restore lại.
        """
        for picking in self:
            # Chỉ bảo vệ phiếu có source_transfer_id (phiếu bước 2)
            if picking.source_transfer_id and 'location_id' in vals:
                current_location = picking.location_id
                new_location_id = vals.get('location_id')
                
                # Nếu location hiện tại là transit và đang bị thay đổi
                if current_location and current_location.usage == 'transit':
                    new_location = self.env['stock.location'].browse(new_location_id) if new_location_id else False
                    
                    # Nếu location mới KHÔNG phải transit, ngăn việc thay đổi
                    if new_location and new_location.usage != 'transit':
                        _logger.warning(f"WRITE PROTECTION: Ngăn thay đổi location_id từ Transit ({current_location.id}) sang {new_location.id}")
                        # Xóa location_id khỏi vals để không ghi đè
                        vals = dict(vals)  # Copy để không ảnh hưởng original
                        del vals['location_id']
        
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        """
        Override create để đảm bảo location_id được set đúng cho phiếu có source_transfer_id.
        """
        result = super().create(vals_list)
        
        # Sau khi tạo, kiểm tra và log
        for picking in result:
            if picking.source_transfer_id:
                _logger.warning(f"CREATE: Phiếu {picking.name} có source_transfer_id={picking.source_transfer_id.id}, location_id={picking.location_id.id}")
        
        return result

    def read(self, fields=None, load='_classic_read'):
        """
        Override read để tự động fix location_id trong DB cho phiếu transit bước 2.
        Chỉ fix DB, không modify result để tránh format issues.
        """
        # Trước khi read, kiểm tra và fix DB nếu cần
        for picking in self:
            if not picking.id:
                continue
            
            # Check trực tiếp từ DB
            self.env.cr.execute("""
                SELECT sp.source_transfer_id, sp.location_id, sp_src.location_dest_id
                FROM stock_picking sp
                LEFT JOIN stock_picking sp_src ON sp.source_transfer_id = sp_src.id
                WHERE sp.id = %s
            """, (picking.id,))
            db_row = self.env.cr.fetchone()
            
            if db_row and db_row[0]:  # Có source_transfer_id
                source_transfer_id = db_row[0]
                db_location_id = db_row[1]
                correct_location_id = db_row[2]  # location_dest_id của phiếu nguồn = Transit
                
                # Nếu location_id hiện tại KHÔNG PHẢI là location đúng
                if correct_location_id and db_location_id != correct_location_id:
                    _logger.warning(f"READ AUTO-FIX: Phiếu {picking.id}, sửa location_id từ {db_location_id} về {correct_location_id}")
                    
                    # Auto-fix DB
                    self.env.cr.execute("""
                        UPDATE stock_picking SET location_id = %s WHERE id = %s
                    """, (correct_location_id, picking.id))
                    self.env.cr.execute("""
                        UPDATE stock_move SET location_id = %s WHERE picking_id = %s
                    """, (correct_location_id, picking.id))
                    self.env.cr.execute("""
                        UPDATE stock_move_line SET location_id = %s WHERE picking_id = %s
                    """, (correct_location_id, picking.id))
                    
                    # Invalidate cache để Odoo đọc lại từ DB
                    picking.invalidate_recordset(['location_id'])
                    picking.move_ids.invalidate_recordset(['location_id'])
                    if picking.move_line_ids:
                        picking.move_line_ids.invalidate_recordset(['location_id'])
        
        # Gọi super để Odoo đọc từ DB đã được fix
        return super().read(fields=fields, load=load)

    # ---------------- Helper ----------------
    def _is_inter_warehouse_transit(self, location):
        """Chỉ nhận 'Physical Locations/Inter-warehouse transit' (Tiếng Anh) 
        hoặc 'Vị trí vật lý/Trung chuyển liên kho' (Tiếng Việt).
        Ưu tiên check theo complete_name; fallback usage='transit'.
        """
        if not location:
            return False
        
        complete_name = (location.complete_name or "").strip().lower()
        
        # Danh sách các tên được chấp nhận (mapping Việt - Anh)
        accepted_names = [
            "physical locations/inter-warehouse transit",
            "vị trí vật lý/trung chuyển liên kho",
            "kho trung gian"
        ]
        
        name_ok = any(complete_name.endswith(name) or complete_name == name for name in accepted_names)
        
        return name_ok or (location.usage == "transit" and ("inter-warehouse transit" in complete_name or "trung chuyển liên kho" in complete_name or "kho trung gian" in complete_name))

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
                
                # đánh dấu để tránh tự đẻ thêm - SỬ DỤNG SQL ĐỂ TRÁNH TRIGGER ONCHANGE
                self.env.cr.execute("""
                    UPDATE stock_picking SET second_transfer_created = TRUE WHERE id = %s
                """, (new_picking.id,))
                self.env.cr.execute("""
                    UPDATE stock_picking SET second_transfer_created = TRUE WHERE id = %s
                """, (picking.id,))

                origin_link = Markup('<a href="#" data-oe-model="stock.picking" data-oe-id="%d">%s</a>') % (
                    picking.id, picking.name
                )
                new_link = Markup('<a href="#" data-oe-model="stock.picking" data-oe-id="%d">%s</a>') % (
                    new_picking.id, new_picking.name
                )
                
                # Lấy thông tin kho để hiển thị
                src_warehouse = picking.picking_type_id.warehouse_id.name if picking.picking_type_id.warehouse_id else "N/A"
                dest_warehouse = picking_type_id.warehouse_id.name if picking_type_id.warehouse_id else "N/A"

                # Message cho phiếu 2 (phiếu nhận)
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
                new_picking.source_transfer_id = picking.id

                # Message cho phiếu 1 (phiếu xuất)
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
                
                picking.message_post(
                    body=picking_msg,
                    message_type="notification",
                    subtype_xmlid="mail.mt_note",
                )

                # Đồng bộ Liên hệ giữa 2 phiếu theo kho
                picking.write({"partner_id": picking_type_id.warehouse_id.partner_id.id})
                new_picking.write({"partner_id": picking.picking_type_id.warehouse_id.partner_id.id})
                
                # ========= FINAL FIX: SQL UPDATE Ở CUỐI CÙNG =========
                # Đặt SAU tất cả write operations để tránh bị onchange ghi đè
                _logger.warning(f"FINAL SQL UPDATE với transit_location.id = {transit_location.id}")
                self.env.cr.execute("""
                    UPDATE stock_picking SET location_id = %s WHERE id = %s
                """, (transit_location.id, new_picking.id))
                self.env.cr.execute("""
                    UPDATE stock_move SET location_id = %s WHERE picking_id = %s
                """, (transit_location.id, new_picking.id))
                self.env.cr.execute("""
                    UPDATE stock_move_line SET location_id = %s WHERE picking_id = %s
                """, (transit_location.id, new_picking.id))
                
                # Verify in DB
                self.env.cr.execute("SELECT location_id FROM stock_picking WHERE id = %s", (new_picking.id,))
                db_check = self.env.cr.fetchone()
                _logger.warning(f"VERIFY DB: Phiếu {new_picking.id} có location_id = {db_check[0] if db_check else 'NULL'}")
                
                _logger.warning("TRANSIT TRANSFER DEBUG - KẾT THÚC")
                _logger.warning("="*50)
                
                return new_picking

    def copy_move_lines(self, source_picking, target_picking):
        """Sao chép move và move lines (bao gồm kiện hàng) sang phiếu mới."""
        for move in source_picking.move_ids:
            # Tạo move mới ở trạng thái draft cho phiếu bước 2
            new_move = move.copy(
                {
                    "picking_id": target_picking.id,
                    "location_id": target_picking.location_id.id,
                    "location_dest_id": target_picking.location_dest_id.id,
                    "state": "draft",
                    # Không copy move lines mặc định từ move.copy để ta tự tạo chính xác theo kiện
                    "move_line_ids": [],
                }
            )
            
            # Duyệt qua các chi tiết dịch chuyển của phiếu nguồn (phiếu đã validate)
            # Lấy các dòng có số lượng đã xử lý (quantity > 0)
            for line in move.move_line_ids.filtered(lambda l: l.quantity > 0):
                # result_package_id của bước 1 sẽ trở thành package_id (kiện nguồn) của bước 2
                # và đồng thời là result_package_id để giữ nguyên kiện hàng cho đến đích cuối
                self.env["stock.move.line"].create({
                    "picking_id": target_picking.id,
                    "move_id": new_move.id,
                    "product_id": line.product_id.id,
                    "product_uom_id": line.product_uom_id.id,
                    "quantity": line.quantity,
                    "location_id": target_picking.location_id.id,
                    "location_dest_id": target_picking.location_dest_id.id,
                    "package_id": line.result_package_id.id if line.result_package_id else False,
                    "result_package_id": line.result_package_id.id if line.result_package_id else False,
                })

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

                # Lấy loại hoạt động tương ứng với cấu hình nhập kho (reception_steps)
                if warehouse.reception_steps == 'one_step':
                    next_operation = warehouse.int_type_id
                else:
                    next_operation = warehouse.in_type_id

                if not next_operation:
                    raise UserError(_("Không tìm thấy loại hoạt động tương ứng cho kho %s") % warehouse.name)

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
        _logger.warning(f"POST-VALIDATE: pickings_need_second_transfer count = {len(pickings_need_second_transfer)}")
        for info in pickings_need_second_transfer:
            picking = info['picking']
            # Refresh để lấy state mới nhất từ DB
            picking.invalidate_recordset(['state'])
            _logger.warning(f"POST-VALIDATE: Picking {picking.id} state = {picking.state}")
            # Chỉ tạo phiếu bước 2 cho phiếu đã validate (state = done)
            if picking.state == 'done':
                _logger.warning(f"POST-VALIDATE: Tạo phiếu 2 cho picking {picking.id}")
                picking.create_second_transfer_wizard(
                    info['final_dest_location_id'],
                    info['next_operation']
                )
            else:
                _logger.warning(f"POST-VALIDATE: SKIP - Picking {picking.id} không phải state=done")

        return result
