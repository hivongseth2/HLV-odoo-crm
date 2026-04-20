import logging
from odoo import models, fields, api
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)

# Fields whose changes should trigger a real-time dashboard refresh
_NOTIFY_FIELDS = {
    'state', 'picking_ids', 'delivery_status', 'amount_total',
    'commitment_date', 'x_plan_need_cancel', 'x_plan_unread_message',
    'x_picking_slip_printed', 'x_studio_delivery_type', 'x_studio_htgh',
    'tag_ids', 'order_line',
}


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    x_plan_need_cancel = fields.Boolean(
        string='Cần hủy (Báo cáo)',
        default=False,
        copy=False,
        help='Được đánh dấu khi người dùng báo cáo đơn hàng cần hủy từ trang sale_plan',
    )
    
    x_plan_unread_message = fields.Boolean(
        string='Có tin nhắn mới',
        default=False,
        copy=False,
        help='Được đánh dấu khi người dùng public gửi tin nhắn qua sale_plan',
    )

    x_picking_slip_printed = fields.Boolean(
        string='Đã in phiếu lấy hàng',
        default=False,
        copy=False,
        help='Được đánh dấu tự động khi phiếu lấy hàng được in từ màn hình điều phối',
    )

    @api.model
    def prepare_transfer_modal_data(self, sale_order_ids=None):
        """Chuẩn bị dữ liệu modal tạo phiếu luân chuyển."""
        if not sale_order_ids:
            return {'warehouses': [], 'all_partners': []}
        return self.env['hlv.delivery.planner.service'].prepare_transfer_modal_data(
            [int(x) for x in sale_order_ids]
        )

    @api.model
    def create_transfer_pickings(self, warehouse_selections=None):
        """Tạo phiếu luân chuyển nội bộ."""
        if not warehouse_selections:
            return {'created': [], 'errors': []}
        return self.env['hlv.delivery.planner.service'].create_transfer_pickings(
            warehouse_selections
        )

    @api.model
    def prepare_relocation_data(self, sale_order_ids=None):
        """Chuẩn bị dữ liệu modal chuyển vị trí."""
        if not sale_order_ids:
            return {'orders': [], 'dest_locations': [], 'default_dest_location_id': False}
        return self.env['hlv.delivery.planner.service'].prepare_relocation_data(
            [int(x) for x in sale_order_ids]
        )

    @api.model
    def create_relocation_pickings(self, relocation_data=None):
        """Tạo phiếu chuyển vị trí nội bộ."""
        if not relocation_data:
            return {'created': [], 'errors': []}
        return self.env['hlv.delivery.planner.service'].create_relocation_pickings(
            relocation_data
        )

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        # Notify when new confirmed orders are created (e.g. from MISA import)
        if any(o.state in ('sale', 'done') for o in orders):
            orders._notify_delivery_planner_changed()
        return orders

    def write(self, vals):
        res = super().write(vals)
        if vals and _NOTIFY_FIELDS.intersection(vals.keys()):
            self._notify_delivery_planner_changed()
        return res

    def _notify_delivery_planner_changed(self):
        """Send bus notification so the delivery planner dashboard refreshes instantly.
        Uses context flag to send at most ONE notification per request cycle."""
        if self.env.context.get('_dp_notified'):
            return
        try:
            self.env['bus.bus']._sendone(
                'delivery_planner_channel',
                'delivery_planner_data_changed',
                {'source': 'sale.order'},
            )
            # Flag this request so cascading model writes don't send duplicates
            self.env.context = dict(self.env.context, _dp_notified=True)
        except Exception:
            _logger.debug('Failed to send delivery_planner_data_changed notification', exc_info=True)

    @api.model
    def get_delivery_dashboard_data(self, search_query='', filter_warehouse_id='all', filter_delivery_status='all', filter_stock_status='all', filter_packing_status='all', filter_date_from='', filter_date_to='', filter_po_date_from='', filter_po_date_to='', filter_po_status='all', filter_done_date_from='', filter_done_date_to='', filter_saler_code='', filter_htgh='', filter_delivery_type='all', filter_tag_ids='', limit=12, offset=0, show_completed=False, filter_need_transfer=False, filter_new_orders=False):
        return self.env['hlv.delivery.planner.service'].get_dashboard_data(
            search_query=search_query,
            filter_warehouse_id=filter_warehouse_id,
            filter_delivery_status=filter_delivery_status,
            filter_stock_status=filter_stock_status,
            filter_packing_status=filter_packing_status,
            filter_date_from=filter_date_from,
            filter_date_to=filter_date_to,
            filter_po_date_from=filter_po_date_from,
            filter_po_date_to=filter_po_date_to,
            filter_po_status=filter_po_status,
            filter_done_date_from=filter_done_date_from,
            filter_done_date_to=filter_done_date_to,
            filter_saler_code=filter_saler_code,
            filter_htgh=filter_htgh,
            filter_delivery_type=filter_delivery_type,
            filter_tag_ids=filter_tag_ids,
            limit=limit,
            offset=offset,
            show_completed=show_completed,
            filter_need_transfer=filter_need_transfer,
            filter_new_orders=filter_new_orders,
        )
