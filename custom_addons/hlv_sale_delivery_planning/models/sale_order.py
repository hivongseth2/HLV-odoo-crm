from odoo import models, fields, api
from dateutil.relativedelta import relativedelta

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model
    def get_delivery_dashboard_data(self, search_query='', filter_warehouse_id='all', filter_delivery_status='all', filter_stock_status='all', filter_packing_status='all', filter_date_from='', filter_date_to='', filter_po_date_from='', filter_po_date_to='', filter_po_status='all', filter_saler_code='', limit=12, offset=0):
        """
        Fetch SOs and matching POs to display on the OWL dashboard.
        Delegated to Service Layer (models.AbstractModel 'hlv.delivery.planner.service').
        """
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
            limit=limit,
            offset=offset
        )
