from odoo import models, api


class DeliveryPlannerService(models.AbstractModel):
    _name = 'hlv.delivery.planner.service'
    _description = 'Delivery Planner Dashboard Service'

    @api.model
    def get_dashboard_data(
        self,
        search_query='', filter_warehouse_id='all',
        filter_delivery_status='all', filter_stock_status='all',
        filter_packing_status='all', filter_date_from='', filter_date_to='',
        filter_po_date_from='', filter_po_date_to='', filter_po_status='all',
        limit=12, offset=0, filter_saler_code='',
        filter_htgh='', filter_delivery_type='all', filter_tag_ids='',
        show_completed=False, filter_need_transfer=False,
    ):
        """
        Äiá»ƒm vÃ o chÃ­nh: tá»•ng há»£p dá»¯ liá»‡u dashboard giao hÃ ng.
        Logic chi tiáº¿t Ä‘Æ°á»£c á»§y quyá»n cho tá»«ng mixin service.
        """
        domain = self._build_search_domain(
            search_query, filter_warehouse_id,
            filter_delivery_status, filter_date_from, filter_date_to,
            filter_saler_code=filter_saler_code,
            filter_htgh=filter_htgh,
            filter_delivery_type=filter_delivery_type,
            filter_tag_ids=filter_tag_ids,
        )
        sales = self.env['sale.order'].search(
            domain,
            order='x_studio_misa_order_date desc nulls last, create_date desc, commitment_date asc, date_order desc'
        )

        sales, matched_ids, dashboard_stats, product_availabilities, so_status_dict = \
            self._calculate_po_and_stock_status(
                sales, filter_po_date_from, filter_po_date_to,
                filter_po_status, filter_delivery_status, filter_stock_status, filter_packing_status,
                show_completed=show_completed,
                filter_need_transfer=filter_need_transfer,
            )

        total_count = len(matched_ids)
        page_sales = self.env['sale.order'].browse(
            matched_ids[int(offset): int(offset) + int(limit)]
        )

        po_by_origin = self._fetch_pos_for_sales(page_sales)
        att_by_picking = self._fetch_attachments_for_pickings(page_sales.mapped('picking_ids').ids)
        so_packages_dict = self._fetch_packages_for_sales(page_sales)

        result = [
            self._format_dashboard_order(
                so, po_by_origin, product_availabilities,
                att_by_picking, so_packages_dict, so_status_dict.get(so.id, {}),
            )
            for so in page_sales
        ]
        warehouses = self.env['stock.warehouse'].search_read([], ['id', 'name'])
        tags = self.env['crm.tag'].search_read([], ['id', 'name'])

        return {
            'orders': result,
            'warehouses': warehouses,
            'tags': tags,
            'total_count': total_count,
            'dashboard_stats': dashboard_stats,
        }


