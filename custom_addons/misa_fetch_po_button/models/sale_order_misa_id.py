# models/sale_order_misa_id.py
import pytz

from dateutil.parser import parse as dtparse
from odoo import models, fields, api, _
from odoo.exceptions import UserError


BUSINESS_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    misa_id = fields.Char(string="MISA ID", copy=False, index=True)
    misa_sale_edit_locked = fields.Boolean(
        string="Sale đang chỉnh sửa trên CRM",
        default=False,
        copy=False,
        index=True,
    )
    misa_sale_edit_locked_at = fields.Datetime(
        string="Bắt đầu chỉnh sửa lúc",
        copy=False,
        readonly=True,
    )
    misa_qty_sync_pending = fields.Boolean(
        string="Chờ kho duyệt thay đổi số lượng",
        default=False,
        copy=False,
        index=True,
    )
    misa_qty_sync_pending_at = fields.Datetime(
        string="Thời điểm MISA thay đổi số lượng",
        copy=False,
        readonly=True,
    )
    misa_qty_sync_pending_summary = fields.Text(
        string="Chi tiết thay đổi số lượng MISA",
        copy=False,
        readonly=True,
    )
    misa_qty_sync_pending_snapshot = fields.Json(
        string="Snapshot dòng MISA chờ kho duyệt",
        copy=False,
        readonly=True,
        help="Dữ liệu dòng MISA đã chuẩn hóa tại lần đồng bộ gần nhất, dùng để duyệt mà không fetch CRM lần nữa.",
    )
    misa_qty_sync_pending_history_id = fields.Many2one(
        'misa.sale.sync.snapshot',
        string="Phiên bản MISA đang chờ duyệt",
        copy=False,
        readonly=True,
        ondelete='set null',
    )
    misa_sync_snapshot_ids = fields.One2many(
        'misa.sale.sync.snapshot',
        'sale_order_id',
        string="Lịch sử thay đổi MISA",
    )
    misa_sync_snapshot_count = fields.Integer(
        string="Số phiên bản MISA",
        compute='_compute_misa_sync_snapshot_count',
    )

    def _compute_misa_sync_snapshot_count(self):
        for order in self:
            order.misa_sync_snapshot_count = len(order.misa_sync_snapshot_ids)

    def action_view_misa_sync_snapshots(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'misa_fetch_po_button.action_misa_sale_sync_snapshot'
        )
        action['domain'] = [('sale_order_id', '=', self.id)]
        action['context'] = {
            'default_sale_order_id': self.id,
            'create': False,
        }
        return action

    def action_misa_start_sale_edit(self):
        """Khóa xác nhận OUT trong lúc sale sửa CRM; PICK/PACK vẫn hoạt động."""
        self.ensure_one()
        order = self.sudo()
        if order.state == 'cancel':
            raise UserError(_("Đơn bán đã hủy nên không thể bắt đầu chỉnh sửa."))
        if not order.misa_sale_edit_locked:
            now = fields.Datetime.now()
            order.write({
                'misa_sale_edit_locked': True,
                'misa_sale_edit_locked_at': now,
            })
            order._misa_notify_warehouse(
                _("Sale bắt đầu chỉnh sửa đơn %s trên CRM. Phiếu OUT tạm khóa xác nhận; PICK/PACK vẫn xử lý bình thường.")
                % order.name
            )
        return order

    def _misa_clear_sale_edit_lock(self):
        locked_orders = self.sudo().filtered('misa_sale_edit_locked')
        if locked_orders:
            locked_orders.write({
                'misa_sale_edit_locked': False,
                'misa_sale_edit_locked_at': False,
            })
        return True

    def action_cancel(self):
        result = super().action_cancel()
        self._misa_clear_sale_edit_lock()
        return result


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    note = fields.Text(string="Note")
    misa_crm_line_id = fields.Char(
        string="CRM Line ID",
        copy=False,
        index=True,
        help="ID duy nhất của dòng sản phẩm trong AMIS CRM, dùng để đồng bộ đúng dòng.",
    )
    misa_sync_change_ids = fields.One2many(
        'misa.sale.sync.snapshot.line',
        'sale_order_line_id',
        string="Lịch sử thay đổi MISA",
    )
    misa_sync_change_count = fields.Integer(
        string="Số thay đổi MISA",
        compute='_compute_misa_sync_change_count',
    )

    def _misa_sync_change_domain(self):
        self.ensure_one()
        direct_domain = ('sale_order_line_id', '=', self.id)
        if not self.misa_crm_line_id:
            return [direct_domain]
        # Fallback CRM Line ID giúp đọc được cả lịch sử tạo trước khi có liên kết SOL trực tiếp.
        return [
            '|',
            direct_domain,
            '&', ('sale_order_line_id', '=', False),
            '&', ('snapshot_id.sale_order_id', '=', self.order_id.id),
            ('crm_line_id', '=', self.misa_crm_line_id),
        ]

    def _compute_misa_sync_change_count(self):
        HistoryLine = self.env['misa.sale.sync.snapshot.line']
        for line in self:
            line.misa_sync_change_count = HistoryLine.search_count(
                line._misa_sync_change_domain()
            ) if line.id else 0

    def action_view_misa_sync_changes(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'misa_fetch_po_button.action_misa_sale_sync_snapshot_line'
        )
        action['domain'] = self._misa_sync_change_domain()
        action['context'] = {'create': False}
        return action


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    misa_sale_qty_sync_pending = fields.Boolean(
        related='sale_id.misa_qty_sync_pending',
        string="SO chờ duyệt SL MISA",
        readonly=True,
    )
    misa_sale_qty_sync_pending_summary = fields.Text(
        related='sale_id.misa_qty_sync_pending_summary',
        string="Thay đổi số lượng MISA",
        readonly=True,
    )
    misa_sale_edit_locked = fields.Boolean(
        related='sale_id.misa_sale_edit_locked',
        string="Sale đang chỉnh sửa trên CRM",
        readonly=True,
    )
    misa_sale_edit_locked_at = fields.Datetime(
        related='sale_id.misa_sale_edit_locked_at',
        string="Sale bắt đầu chỉnh sửa lúc",
        readonly=True,
    )

    def button_validate(self):
        blocked = self.filtered(
            lambda picking: picking.picking_type_id.code == 'outgoing'
            and picking.sale_id
            and picking.sale_id.misa_sale_edit_locked
        )
        if blocked:
            details = ', '.join(
                "%s (%s)" % (picking.name, picking.sale_id.name)
                for picking in blocked
            )
            raise UserError(_(
                "Không thể xác nhận phiếu xuất kho %s vì sale đang chỉnh sửa đơn trên CRM. "
                "PICK/PACK vẫn được xử lý bình thường; hãy chờ sale đồng bộ và kho áp dụng bản sửa."
            ) % details)
        return super().button_validate()

    def action_approve_misa_quantity_sync(self):
        self.ensure_one()
        if not self.sale_id:
            return False
        return self.sale_id.action_approve_misa_quantity_sync()


class MisaSaleSyncSnapshot(models.Model):
    _name = 'misa.sale.sync.snapshot'
    _description = 'Lịch sử snapshot đồng bộ Sale Order từ MISA'
    _order = 'fetched_at desc, id desc'

    name = fields.Char(string="Phiên bản", compute='_compute_name', readonly=True)
    sale_order_id = fields.Many2one(
        'sale.order', string="Đơn bán", required=True, index=True, ondelete='cascade', readonly=True,
    )
    misa_order_id = fields.Char(string="MISA ID", index=True, readonly=True)
    fetched_at = fields.Datetime(string="Nhận thay đổi lúc", required=True, readonly=True)
    fetched_by_id = fields.Many2one('res.users', string="Nhận bởi", readonly=True)
    crm_owner = fields.Char(string="Sale phụ trách trên CRM", readonly=True)
    crm_modified_by = fields.Char(string="Người sửa trên CRM", readonly=True)
    crm_modified_at = fields.Datetime(string="CRM sửa lúc", readonly=True)
    crm_modified_at_raw = fields.Char(string="Giờ CRM gốc", readonly=True)
    crm_modified_at_display = fields.Char(
        string="CRM sửa lúc",
        compute='_compute_crm_modified_at_display',
        readonly=True,
    )
    state = fields.Selection([
        ('pending', 'Chờ kho duyệt'),
        ('superseded', 'Đã được phiên bản mới thay thế'),
        ('applied', 'Đã áp dụng'),
        ('cancelled', 'Đã hủy'),
    ], string="Trạng thái", required=True, default='pending', index=True, readonly=True)
    summary = fields.Text(string="Tóm tắt thay đổi", readonly=True)
    warehouse_summary = fields.Text(string="Tóm tắt số lượng chờ duyệt", readonly=True)
    snapshot_payload = fields.Json(string="Snapshot đã chuẩn hóa", readonly=True)
    line_ids = fields.One2many(
        'misa.sale.sync.snapshot.line', 'snapshot_id', string="Chi tiết thay đổi", readonly=True,
    )
    change_count = fields.Integer(string="Số thay đổi", readonly=True)
    approved_at = fields.Datetime(string="Duyệt lúc", readonly=True)
    approved_by_id = fields.Many2one('res.users', string="Người duyệt", readonly=True)
    replaced_by_id = fields.Many2one(
        'misa.sale.sync.snapshot', string="Được thay bởi", readonly=True, ondelete='set null',
    )

    @api.depends('sale_order_id.name', 'fetched_at')
    def _compute_name(self):
        for snapshot in self:
            order_name = snapshot.sale_order_id.name or _('Đơn bán')
            if snapshot.fetched_at:
                utc_dt = snapshot.fetched_at
                if utc_dt.tzinfo is None:
                    utc_dt = pytz.UTC.localize(utc_dt)
                local_dt = utc_dt.astimezone(BUSINESS_TZ)
                snapshot.name = "%s / %s" % (
                    order_name,
                    local_dt.strftime('%Y-%m-%d %H:%M:%S'),
                )
            else:
                snapshot.name = _("%s / Snapshot MISA") % order_name

    @api.depends('crm_modified_at_raw', 'crm_modified_at')
    def _compute_crm_modified_at_display(self):
        for snapshot in self:
            wall_time = False
            if snapshot.crm_modified_at_raw:
                try:
                    # MISA gửi giờ nghiệp vụ Việt Nam; bỏ timezone marker nếu có.
                    wall_time = dtparse(snapshot.crm_modified_at_raw).replace(tzinfo=None)
                except Exception:
                    wall_time = False
            elif snapshot.crm_modified_at:
                # Tương thích lịch sử cũ: giá trị từng được lưu thẳng như UTC dù thực chất là giờ CRM.
                wall_time = snapshot.crm_modified_at.replace(tzinfo=None)
            snapshot.crm_modified_at_display = (
                wall_time.strftime('%d/%m/%Y %H:%M:%S') if wall_time else False
            )

    def _check_stock_approval_user(self):
        if not self.env.user.has_group('stock.group_stock_user'):
            raise UserError(_("Chỉ người dùng kho mới được xử lý snapshot MISA."))

    def action_approve_snapshot(self):
        self.ensure_one()
        self._check_stock_approval_user()
        if self.state != 'pending':
            raise UserError(_("Chỉ snapshot đang chờ duyệt mới được xác nhận."))
        if self.sale_order_id.misa_qty_sync_pending_history_id != self:
            raise UserError(_("Snapshot này không còn là phiên bản đang chờ duyệt mới nhất."))
        return self.sale_order_id.action_approve_misa_quantity_sync()

    def action_cancel_snapshot(self):
        self.ensure_one()
        self._check_stock_approval_user()
        if self.state != 'pending':
            raise UserError(_("Chỉ snapshot đang chờ duyệt mới được hủy."))
        order = self.sale_order_id.sudo()
        self.sudo().write({'state': 'cancelled'})
        if order.misa_qty_sync_pending_history_id == self:
            order.write({
                'misa_qty_sync_pending': False,
                'misa_qty_sync_pending_at': False,
                'misa_qty_sync_pending_summary': False,
                'misa_qty_sync_pending_snapshot': False,
                'misa_qty_sync_pending_history_id': False,
            })
            order._misa_clear_sale_edit_lock()
        order._misa_notify_warehouse(
            _("Kho (%s) đã hủy snapshot MISA %s của đơn %s.")
            % (self.env.user.name, self.name, order.name)
        )
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_restore_snapshot(self):
        self.ensure_one()
        self._check_stock_approval_user()
        if self.state != 'cancelled':
            raise UserError(_("Chỉ snapshot đã hủy mới được đưa lại về chờ duyệt."))
        order = self.sale_order_id.sudo()
        if order.state == 'cancel':
            raise UserError(_("Đơn bán đã hủy nên không thể phục hồi snapshot chờ duyệt."))
        active_snapshot = order.misa_qty_sync_pending_history_id
        if active_snapshot and active_snapshot != self and active_snapshot.state == 'pending':
            raise UserError(_(
                "Đơn đã có snapshot mới hơn đang chờ duyệt (%s); không thể phục hồi bản cũ."
            ) % active_snapshot.name)
        if not isinstance(self.snapshot_payload, list):
            raise UserError(_("Snapshot không còn payload hợp lệ để phục hồi."))
        order.action_misa_start_sale_edit()
        now = fields.Datetime.now()
        restored = self.sudo().create({
            'sale_order_id': order.id,
            'misa_order_id': self.misa_order_id,
            'fetched_at': now,
            'fetched_by_id': self.env.user.id,
            'crm_owner': self.crm_owner,
            'crm_modified_by': self.crm_modified_by,
            'crm_modified_at': self.crm_modified_at,
            'crm_modified_at_raw': self.crm_modified_at_raw,
            'state': 'pending',
            'summary': self.summary,
            'warehouse_summary': self.warehouse_summary,
            'snapshot_payload': self.snapshot_payload,
            'change_count': self.change_count,
            'line_ids': [(0, 0, {
                'change_type': line.change_type,
                'crm_line_id': line.crm_line_id,
                'sale_order_line_id': line.sale_order_line_id.id,
                'product_id': line.product_id.id,
                'product_code': line.product_code,
                'field_name': line.field_name,
                'old_value': line.old_value,
                'new_value': line.new_value,
            }) for line in self.line_ids],
        })
        self.sudo().write({'replaced_by_id': restored.id})
        order.write({
            'misa_qty_sync_pending': True,
            'misa_qty_sync_pending_at': now,
            'misa_qty_sync_pending_summary': restored.warehouse_summary or restored.summary,
            'misa_qty_sync_pending_snapshot': restored.snapshot_payload,
            'misa_qty_sync_pending_history_id': restored.id,
        })
        order._misa_notify_warehouse(
            _("Kho (%s) đã nhân bản snapshot MISA %s thành %s và đưa về chờ duyệt.")
            % (self.env.user.name, self.name, restored.name),
            restored.warehouse_summary or restored.summary,
        )
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'misa.sale.sync.snapshot',
            'view_mode': 'form',
            'res_id': restored.id,
            'target': 'current',
        }


class MisaSaleSyncSnapshotLine(models.Model):
    _name = 'misa.sale.sync.snapshot.line'
    _description = 'Chi tiết thay đổi Sale Order trong snapshot MISA'
    _order = 'id desc'

    snapshot_id = fields.Many2one(
        'misa.sale.sync.snapshot', string="Phiên bản", required=True, index=True,
        ondelete='cascade', readonly=True,
    )
    sale_order_line_id = fields.Many2one(
        'sale.order.line', string="Dòng đơn bán", index=True, readonly=True, ondelete='set null',
    )
    change_type = fields.Selection([
        ('add', 'Thêm dòng'),
        ('update', 'Cập nhật'),
        ('remove', 'Xóa/giảm dòng'),
    ], string="Loại thay đổi", required=True, readonly=True)
    crm_line_id = fields.Char(string="CRM Line ID", index=True, readonly=True)
    product_id = fields.Many2one('product.product', string="Sản phẩm", readonly=True, ondelete='set null')
    product_code = fields.Char(string="Mã sản phẩm", readonly=True)
    field_name = fields.Char(string="Nội dung sửa", required=True, readonly=True)
    old_value = fields.Text(string="Trước thay đổi", readonly=True)
    new_value = fields.Text(string="Sau thay đổi", readonly=True)
