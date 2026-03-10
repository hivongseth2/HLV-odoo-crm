from odoo import models


class DeliveryPlannerServiceDomain(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    def _build_search_domain(
        self, search_query, filter_warehouse_id,
        filter_delivery_status, filter_date_from, filter_date_to,
    ):
        """Xây dựng domain tìm kiếm Sale Order dựa trên các bộ lọc."""
        domain = [('state', 'in', ['sale', 'done'])]

        # Luu y: filter delivery duoc xu ly o service layer bang real_delivery_status
        # de dong bo voi kanban/card (tranh lech voi field delivery_status goc cua SO).

        if filter_warehouse_id != 'all':
            domain += [('warehouse_id', '=', int(filter_warehouse_id))]

        if search_query:
            domain += ['|',
                       ('name', 'ilike', search_query),
                       ('partner_id.name', 'ilike', search_query)]

        if filter_date_from:
            domain += ['|',
                       ('commitment_date', '>=', filter_date_from),
                       '&', ('commitment_date', '=', False),
                       ('date_order', '>=', filter_date_from)]

        if filter_date_to:
            domain += ['|',
                       ('commitment_date', '<=', filter_date_to),
                       '&', ('commitment_date', '=', False),
                       ('date_order', '<=', filter_date_to)]

        return domain
