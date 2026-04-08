from odoo import models, fields, api
from dateutil.relativedelta import relativedelta

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    x_plan_need_cancel = fields.Boolean(
        string='Cần hủy (Báo cáo)',
        default=False,
        copy=False,
        help='Được đánh dấu khi người dùng báo cáo đơn hàng cần hủy từ trang sale_plan',
    )

    @api.model
    def get_delivery_dashboard_data(self, search_query='', filter_warehouse_id='all', filter_delivery_status='all', filter_stock_status='all', filter_packing_status='all', filter_date_from='', filter_date_to='', filter_po_date_from='', filter_po_date_to='', filter_po_status='all', filter_saler_code='', filter_htgh='', filter_delivery_type='all', filter_tag_ids='', limit=12, offset=0, show_completed=False):
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
            filter_saler_code=filter_saler_code,
            filter_htgh=filter_htgh,
            filter_delivery_type=filter_delivery_type,
            filter_tag_ids=filter_tag_ids,
            limit=limit,
            offset=offset,
            show_completed=show_completed,
        )
