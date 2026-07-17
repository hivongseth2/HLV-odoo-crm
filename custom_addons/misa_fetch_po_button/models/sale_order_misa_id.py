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
