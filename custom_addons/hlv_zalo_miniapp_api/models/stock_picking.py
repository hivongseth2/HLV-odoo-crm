# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    x_is_zalo_picking = fields.Boolean(
        string="Phiếu giao hàng Zalo",
        compute="_compute_x_is_zalo_picking_types",
        store=True,
        help="Đánh dấu phiếu kho này thuộc quy trình đơn hàng Zalo Mini App",
    )

    x_is_zalo_outgoing_picking = fields.Boolean(
        string="Phiếu xuất kho Zalo",
        compute="_compute_x_is_zalo_picking_types",
        store=True,
        help="Đánh dấu phiếu kho này là phiếu xuất kho (OUT) thuộc đơn hàng Zalo Mini App",
    )

    x_is_zalo_incoming_return_picking = fields.Boolean(
        string="Phiếu nhập trả hàng Zalo",
        compute="_compute_x_is_zalo_picking_types",
        store=True,
        help="Đánh dấu phiếu kho này là phiếu nhập kho trả hàng (IN) từ phiếu xuất Zalo",
    )

    x_zalo_return_requested = fields.Boolean(
        string="Khách đề nghị đổi/trả Zalo",
        default=False,
        tracking=True,
        help="Khách hàng Zalo Mini App đã gửi yêu cầu đổi/trả cho phiếu xuất kho này",
    )

    x_zalo_return_state = fields.Selection(
        [
            ("pending", "Chờ duyệt"),
            ("approved", "Đã duyệt"),
            ("processing", "Đang xử lý"),
            ("completed", "Hoàn tất"),
            ("rejected", "Từ chối"),
        ],
        string="Trạng thái đổi/trả Zalo",
        default=False,
        tracking=True,
        help="Trạng thái xử lý yêu cầu đổi/trả của phiếu xuất kho Zalo",
    )

    x_zalo_return_type = fields.Selection(
        [
            ("return", "Trả hàng hoàn tiền"),
            ("exchange", "Đổi hàng"),
            ("refund", "Hoàn tiền một phần"),
        ],
        string="Loại đổi/trả Zalo",
        tracking=True,
        help="Phân loại yêu cầu đổi/trả của phiếu xuất kho Zalo",
    )

    x_zalo_return_refund_amount = fields.Float(
        string="Số tiền hoàn lại",
        tracking=True,
        help="Số tiền sẽ hoàn lại cho khách (chỉ áp dụng cho phiếu Zalo)",
    )

    x_zalo_return_category = fields.Selection(
        [
            ("supplier_fault", "Lỗi nhà cung cấp / Vận chuyển"),
            ("customer_demand", "Đổi trả theo nhu cầu"),
        ],
        string="Nhóm nguyên nhân đổi/trả",
        tracking=True,
    )

    x_zalo_product_condition = fields.Selection(
        [
            ("unused", "Chưa qua sử dụng (nguyên tem)"),
            ("used", "Đã qua sử dụng"),
        ],
        string="Tình trạng sản phẩm",
        tracking=True,
    )

    x_zalo_return_note = fields.Text(
        string="Ghi chú đổi/trả Zalo",
        tracking=True,
        help="Ghi chú từ khách hàng Zalo khi yêu cầu đổi/trả",
    )

    x_zalo_return_rejected_reason = fields.Text(
        string="Lý do từ chối",
        tracking=True,
        help="Lý do từ chối yêu cầu đổi/trả Zalo",
    )

    x_zalo_return_picking_id = fields.Many2one(
        "stock.picking",
        string="Phiếu trả hàng (WH/IN)",
        tracking=True,
        help="Phiếu nhập kho trả hàng được tạo từ wizard trả hàng chuẩn Odoo",
    )

    x_zalo_return_completed_date = fields.Datetime(
        string="Ngày hoàn tất đổi/trả Zalo",
        tracking=True,
        help="Thời điểm hoàn tất xử lý đổi/trả phiếu kho Zalo",
    )

    @api.depends("sale_id", "sale_id.partner_id.x_is_zalo_account", "partner_id.x_is_zalo_account", "picking_type_id.code", "origin")
    def _compute_x_is_zalo_picking_types(self):
        for picking in self:
            is_zalo_account = False
            if picking.sale_id and picking.sale_id.partner_id.x_is_zalo_account:
                is_zalo_account = True
            elif picking.partner_id and picking.partner_id.x_is_zalo_account:
                is_zalo_account = True

            code = picking.picking_type_id.code or ""
            is_outgoing = is_zalo_account and code == "outgoing"

            is_incoming_return = False
            if code == "incoming":
                origin_picking = picking._get_origin_outgoing_picking()
                if origin_picking and (origin_picking.x_is_zalo_outgoing_picking or origin_picking.sale_id.partner_id.x_is_zalo_account):
                    is_incoming_return = True

            picking.x_is_zalo_outgoing_picking = is_outgoing
            picking.x_is_zalo_incoming_return_picking = is_incoming_return
            picking.x_is_zalo_picking = is_outgoing or is_incoming_return

    def _get_origin_outgoing_picking(self):
        """Tìm phiếu xuất kho OUT gốc của return picking này."""
        self.ensure_one()
        origin = self.origin or ""
        if not origin:
            return self.env["stock.picking"]
        origin_picking = self.env["stock.picking"].sudo().search([
            ("name", "=", origin),
            ("picking_type_id.code", "=", "outgoing"),
        ], limit=1)
        return origin_picking

    def action_approve_zalo_return(self):
        """Phê duyệt yêu cầu đổi/trả Zalo & mở wizard stock.return.picking chuẩn Odoo (chỉ trên phiếu OUT)."""
        self.ensure_one()
        if not self.x_is_zalo_outgoing_picking:
            raise UserError(_("Chức năng này chỉ áp dụng cho phiếu xuất kho thuộc đơn hàng Zalo Mini App."))
        if not self.x_zalo_return_requested:
            raise UserError(_("Phiếu xuất kho này chưa có yêu cầu đổi/trả từ khách Zalo."))
        if self.x_zalo_return_state and self.x_zalo_return_state not in ("pending", "draft"):
            state_label = dict(self._fields["x_zalo_return_state"].selection).get(self.x_zalo_return_state, self.x_zalo_return_state)
            raise UserError(_("Yêu cầu đổi/trả đã được xử lý (trạng thái: %s).") % state_label)

        self.write({"x_zalo_return_state": "approved"})

        msg = Markup(_("<b>Đã phê duyệt yêu cầu đổi/trả Zalo cho phiếu kho %s</b>")) % self.name
        self.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")
        if self.sale_id:
            self.sale_id.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")

        # Trả về action mở wizard trả hàng chuẩn Odoo (stock.return.picking)
        return {
            "name": _("Trả hàng (Return Picking)"),
            "view_mode": "form",
            "res_model": "stock.return.picking",
            "type": "ir.actions.act_window",
            "target": "new",
            "context": dict(self.env.context, active_id=self.id, active_model="stock.picking"),
        }

    def action_open_reject_wizard(self):
        """Mở wizard nhập lý do từ chối yêu cầu đổi/trả Zalo."""
        self.ensure_one()
        if not self.x_is_zalo_outgoing_picking:
            raise UserError(_("Chức năng này chỉ áp dụng cho phiếu xuất kho Zalo Mini App."))
        if not self.x_zalo_return_requested:
            raise UserError(_("Phiếu xuất kho này chưa có yêu cầu đổi/trả từ khách."))
        if self.x_zalo_return_state and self.x_zalo_return_state not in ("pending", "approved"):
            state_label = dict(self._fields["x_zalo_return_state"].selection).get(self.x_zalo_return_state, self.x_zalo_return_state)
            raise UserError(_("Yêu cầu đổi/trả đã được xử lý (trạng thái: %s).") % state_label)

        return {
            "name": _("Từ chối Yêu cầu Đổi/Trả Zalo"),
            "type": "ir.actions.act_window",
            "res_model": "zalo.return.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_picking_id": self.id,
                "default_reason": self.x_zalo_return_rejected_reason or "",
            },
        }

    def action_reject_zalo_return(self, reason=""):
        """Từ chối yêu cầu đổi/trả Zalo (chỉ trên phiếu OUT)."""
        self.ensure_one()
        if not self.x_is_zalo_outgoing_picking:
            raise UserError(_("Chức năng này chỉ áp dụng cho phiếu xuất kho Zalo Mini App."))
        if not self.x_zalo_return_requested:
            raise UserError(_("Phiếu xuất kho này chưa có yêu cầu đổi/trả từ khách."))
        if self.x_zalo_return_state and self.x_zalo_return_state not in ("pending", "approved"):
            state_label = dict(self._fields["x_zalo_return_state"].selection).get(self.x_zalo_return_state, self.x_zalo_return_state)
            raise UserError(_("Yêu cầu đổi/trả đã được xử lý (trạng thái: %s).") % state_label)

        self.write({
            "x_zalo_return_state": "rejected",
            "x_zalo_return_rejected_reason": reason or "",
        })

        msg = Markup(_("<b>Đã từ chối yêu cầu đổi/trả Zalo cho phiếu kho %s</b>")) % self.name
        if reason:
            msg += Markup(_("<br/>• <b>Lý do:</b> %s")) % reason
        self.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")
        if self.sale_id:
            self.sale_id.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")

    def action_complete_zalo_return(self):
        """Hoàn tất đổi/trả Zalo thủ công (chỉ trên phiếu OUT)."""
        self.ensure_one()
        if not self.x_is_zalo_outgoing_picking:
            raise UserError(_("Chức năng này chỉ áp dụng cho phiếu xuất kho Zalo Mini App."))
        if self.x_zalo_return_state not in ("approved", "processing"):
            raise UserError(_("Yêu cầu đổi/trả chưa được phê duyệt hoặc đang xử lý."))
        self.write({
            "x_zalo_return_state": "completed",
            "x_zalo_return_completed_date": fields.Datetime.now(),
        })
        msg = Markup(_("<b>Đã hoàn tất xử lý đổi/trả Zalo cho phiếu kho %s</b>")) % self.name
        self.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")
        if self.sale_id:
            self.sale_id.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")

    def _send_zalo_return_notifications(self):
        """
        Gửi thông báo chủ động Đa Kênh khi có Yêu cầu Đổi/Trả Zalo Mini App:
        1. Odoo Activity Schedule (`mail.activity`): Giao task cho Salesperson & Managers (hiển thị trên nút Đồng Hồ Odoo).
        2. Direct Chatter Tagging & Live Toast: Tag partner_ids để bắn chuông notification bell Odoo.
        3. Instant Zalo Message Push (`hlv.zalo.stock.notification`): Gửi tin nhắn Zalo về di động cho người quản lý.
        """
        self.ensure_one()
        Param = self.env["ir.config_parameter"].sudo()

        # Lấy danh sách Users được cấu hình nhận thông báo
        configured_user_ids = []
        raw_user_ids = Param.get_param("hlv_zalo_miniapp.return_notify_user_ids", "")
        if raw_user_ids:
            try:
                clean_ids = raw_user_ids.replace("[", "").replace("]", "").split(",")
                configured_user_ids = [int(u.strip()) for u in clean_ids if u.strip().isdigit()]
            except Exception:
                pass

        target_users = self.env["res.users"].sudo().browse(configured_user_ids).filtered(lambda u: u.active)

        # Fallback 1: Nếu không cấu hình user nào, ưu tiên giao cho Sale phụ trách đơn hàng
        if not target_users and self.sale_id and self.sale_id.user_id:
            target_users = self.sale_id.user_id

        # Fallback 2: Nếu vẫn chưa có, lấy admin user
        if not target_users:
            admin_user = self.env.ref("base.user_admin", raise_if_not_found=False) or self.env.user
            target_users = admin_user if admin_user else self.env.user

        # Labels
        cat_label = "Lỗi nhà cung cấp / Vận chuyển" if self.x_zalo_return_category == "supplier_fault" else "Theo nhu cầu khách hàng"
        cond_label = "Chưa qua sử dụng (nguyên tem)" if self.x_zalo_product_condition == "unused" else "Đã qua sử dụng"
        cust_name = self.partner_id.name if self.partner_id else "Khách hàng Zalo"
        cust_phone = self.partner_id.phone or self.partner_id.mobile or ""
        so_name = self.sale_id.name if self.sale_id else self.origin or ""

        # ===== KÊNH 1: Odoo Activity Schedule (`mail.activity`) =====
        activity_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        for user in target_users:
            try:
                existing_activity = self.env["mail.activity"].sudo().search([
                    ("res_model", "=", "stock.picking"),
                    ("res_id", "=", self.id),
                    ("user_id", "=", user.id),
                    ("summary", "ilike", "Yêu cầu Đổi/Trả Zalo"),
                ], limit=1)

                if not existing_activity and activity_type:
                    self.env["mail.activity"].sudo().create({
                        "activity_type_id": activity_type.id,
                        "note": Markup(_(
                            "<b>Yêu cầu Đổi/Trả Hàng từ Zalo Mini App</b><br/>"
                            "• <b>Đơn hàng:</b> %s<br/>"
                            "• <b>Phiếu xuất:</b> %s<br/>"
                            "• <b>Khách hàng:</b> %s (%s)<br/>"
                            "• <b>Phân loại:</b> %s<br/>"
                            "• <b>Tình trạng SP:</b> %s<br/>"
                            "• <b>Ghi chú:</b> %s"
                        )) % (so_name, self.name, cust_name, cust_phone, cat_label, cond_label, self.x_zalo_return_note or "Không có"),
                        "res_id": self.id,
                        "res_model_id": self.env.ref("stock.model_stock_picking").id,
                        "summary": _("⚠️ Yêu cầu Đổi/Trả Zalo: %s") % so_name,
                        "user_id": user.id,
                        "date_deadline": fields.Date.today(),
                    })
            except Exception as e:
                _logger.exception("Lỗi khi tạo Activity đổi/trả Zalo cho user %s: %s", user.id, e)

        # ===== KÊNH 2: Odoo Bus Live Pop-up Toast & Notification Bell =====
        target_partners = target_users.mapped("partner_id")
        if target_partners:
            chatter_msg = Markup(_(
                "🚨 <b>YÊU CẦU ĐỔI/TRẢ HÀNG ZALO MINI APP MỚI</b><br/>"
                "• <b>Đơn hàng:</b> %s<br/>"
                "• <b>Phiếu xuất kho:</b> %s<br/>"
                "• <b>Khách hàng:</b> %s (%s)<br/>"
                "• <b>Phân loại nguyên nhân:</b> %s<br/>"
                "• <b>Tình trạng sản phẩm:</b> %s<br/>"
                "• <b>Ghi chú từ khách:</b> %s"
            )) % (so_name, self.name, cust_name, cust_phone, cat_label, cond_label, self.x_zalo_return_note or "Không có")
            self.message_post(
                body=chatter_msg,
                partner_ids=target_partners.ids,
                message_type="notification",
                subtype_xmlid="mail.mt_comment",
            )

        # ===== KÊNH 3: Instant Zalo Mobile Push (`hlv.zalo.stock.notification`) =====
        try:
            raw_zalo_uids = Param.get_param("hlv_zalo_miniapp.return_zalo_uids", "")
            zalo_recipients = [u.strip() for u in raw_zalo_uids.split(",") if u.strip()]

            # Tìm Zalo Stock Notification Config active
            zalo_config = False
            if "hlv.zalo.stock.notification" in self.env:
                zalo_config = self.env["hlv.zalo.stock.notification"].sudo()._get_active_config()

            if zalo_config and zalo_recipients:
                base_url = Param.get_param("web.base.url", "")
                action_id = self.env.ref("stock.action_picking_tree_all", raise_if_not_found=False)
                action_param = f"/odoo/action-{action_id.id}" if action_id else "/odoo"
                picking_url = f"{base_url}{action_param}/{self.id}"

                zalo_msg = f"🔔 YÊU CẦU ĐỔI/TRẢ HÀNG ZALO MINI APP MỚI\n"
                zalo_msg += f"  • Mã Đơn: {so_name}\n"
                zalo_msg += f"  • Phiếu xuất: {self.name}\n"
                zalo_msg += f"  • Khách hàng: {cust_name} ({cust_phone})\n"
                zalo_msg += f"  • Phân loại: {cat_label}\n"
                zalo_msg += f"  • Tình trạng SP: {cond_label}\n"
                if self.x_zalo_return_note:
                    zalo_msg += f"  • Ghi chú: {self.x_zalo_return_note}\n"
                zalo_msg += f"👉 Mở xem trên Odoo: {picking_url}"

                for uid in zalo_recipients:
                    try:
                        zalo_config.send_notification_message(uid, zalo_msg)
                        _logger.info("✓ Zalo Return Notification sent to UID %s for picking %s", uid, self.name)
                    except Exception as ze:
                        _logger.error("✗ Lỗi gửi Zalo Return Notification tới %s: %s", uid, ze)
        except Exception as ex:
            _logger.exception("Lỗi khi gửi Zalo Return Notification cho picking %s: %s", self.name, ex)

    @api.model
    def create(self, vals):
        """Khi tạo phiếu nhập kho (return picking), tự động link về phiếu xuất kho Zalo gốc."""
        picking = super().create(vals)
        if picking.picking_type_id.code == "incoming":
            origin_picking = picking._get_origin_outgoing_picking()
            if origin_picking and origin_picking.x_zalo_return_requested:
                write_vals = {
                    "x_zalo_return_state": "processing",
                    "x_zalo_return_picking_id": picking.id,
                }
                origin_picking.write(write_vals)
                msg = Markup(_(
                    "<b>Đã tạo phiếu trả hàng %s từ phiếu xuất kho %s - Đổi/trả Zalo</b>"
                )) % (picking.name, origin_picking.name)
                origin_picking.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")
                if origin_picking.sale_id:
                    origin_picking.sale_id.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")
        return picking

    def write(self, vals):
        """Khi phiếu return picking được validate (done) hoặc hủy (cancel), tự động cập nhật trạng thái phiếu OUT Zalo."""
        res = super().write(vals)
        if "state" in vals:
            new_state = vals["state"]
            for picking in self:
                if picking.picking_type_id.code != "incoming":
                    continue
                origin_picking = picking._get_origin_outgoing_picking()
                if not origin_picking or not origin_picking.x_zalo_return_requested:
                    continue

                if new_state == "done" and origin_picking.x_zalo_return_state in ("processing", "approved"):
                    origin_picking.write({
                        "x_zalo_return_state": "completed",
                        "x_zalo_return_completed_date": fields.Datetime.now(),
                    })
                    msg = Markup(_(
                        "<b>Phiếu trả hàng %s đã hoàn tất - Đổi/trả Zalo hoàn thành cho phiếu xuất %s</b>"
                    )) % (picking.name, origin_picking.name)
                    origin_picking.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")
                    if origin_picking.sale_id:
                        origin_picking.sale_id.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")

                elif new_state == "cancel" and origin_picking.x_zalo_return_state in ("processing", "approved"):
                    reason = _("Phiếu kho nhập trả %s đã bị hủy.") % picking.name
                    origin_picking.write({
                        "x_zalo_return_state": "rejected",
                        "x_zalo_return_rejected_reason": reason,
                    })
                    msg = Markup(_(
                        "<b>Phiếu kho trả hàng %s bị hủy - Tự động chuyển Đổi/trả Zalo sang Từ chối cho phiếu xuất %s</b>"
                    )) % (picking.name, origin_picking.name)
                    origin_picking.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")
                    if origin_picking.sale_id:
                        origin_picking.sale_id.message_post(body=msg, message_type="comment", subtype_xmlid="mail.mt_note")
        return res