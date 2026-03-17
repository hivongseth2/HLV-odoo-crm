from odoo import models


class DeliveryPlannerServiceDomain(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    def _build_search_domain(
        self, search_query, filter_warehouse_id,
        filter_delivery_status, filter_date_from, filter_date_to,
        filter_saler_code='', filter_htgh='', filter_delivery_type='all', filter_tag_ids='',
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

        if filter_saler_code:
            domain += [('x_studio_misa_saler_code', 'ilike', filter_saler_code)]

        if filter_htgh:
            domain += [('x_studio_htgh', 'ilike', filter_htgh)]

        if filter_delivery_type and filter_delivery_type != 'all':
            domain += [('x_studio_delivery_type', '=', filter_delivery_type)]

        if filter_tag_ids:
            try:
                tag_id = int(filter_tag_ids)
                domain += [('tag_ids', 'in', [tag_id])]
            except (ValueError, TypeError):
                pass

        return domain
