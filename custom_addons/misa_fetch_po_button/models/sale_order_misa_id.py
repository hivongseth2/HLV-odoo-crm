# models/sale_order_misa_id.py
from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    misa_id = fields.Char(string="MISA ID", copy=False, index=True)
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


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    note = fields.Text(string="Note")
    misa_crm_line_id = fields.Char(
        string="CRM Line ID",
        copy=False,
        index=True,
        help="ID duy nhất của dòng sản phẩm trong AMIS CRM, dùng để đồng bộ đúng dòng.",
    )


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

    def action_approve_misa_quantity_sync(self):
        self.ensure_one()
        if not self.sale_id:
            return False
        return self.sale_id.action_approve_misa_quantity_sync()


class MisaSaleSyncSnapshot(models.Model):
    _name = 'misa.sale.sync.snapshot'
    _description = 'Lịch sử snapshot đồng bộ Sale Order từ MISA'
    _order = 'fetched_at desc, id desc'

    name = fields.Char(string="Phiên bản", required=True, readonly=True)
    sale_order_id = fields.Many2one(
        'sale.order', string="Đơn bán", required=True, index=True, ondelete='cascade', readonly=True,
    )
    misa_order_id = fields.Char(string="MISA ID", index=True, readonly=True)
    fetched_at = fields.Datetime(string="Nhận thay đổi lúc", required=True, readonly=True)
    fetched_by_id = fields.Many2one('res.users', string="Nhận bởi", readonly=True)
    crm_owner = fields.Char(string="Sale phụ trách trên CRM", readonly=True)
    crm_modified_by = fields.Char(string="Người sửa trên CRM", readonly=True)
    crm_modified_at = fields.Datetime(string="CRM sửa lúc", readonly=True)
    state = fields.Selection([
        ('pending', 'Chờ kho duyệt'),
        ('superseded', 'Đã được phiên bản mới thay thế'),
        ('applied', 'Đã áp dụng'),
    ], string="Trạng thái", required=True, default='pending', index=True, readonly=True)
    summary = fields.Text(string="Tóm tắt thay đổi", readonly=True)
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


class MisaSaleSyncSnapshotLine(models.Model):
    _name = 'misa.sale.sync.snapshot.line'
    _description = 'Chi tiết thay đổi Sale Order trong snapshot MISA'
    _order = 'id'

    snapshot_id = fields.Many2one(
        'misa.sale.sync.snapshot', string="Phiên bản", required=True, index=True,
        ondelete='cascade', readonly=True,
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
