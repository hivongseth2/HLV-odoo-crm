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
            # Hỗ trợ nhiều keyword phân tách bằng dấu phẩy.
            # Prefix "!" = NOT LIKE (loại trừ).
            # VD: "ghn,cpn" → chứa "ghn" HOẶC "cpn"
            # VD: "!ghn,!cpn" → KHÔNG chứa "ghn" VÀ KHÔNG chứa "cpn"
            # VD: "ghn,!j&t" → chứa "ghn" VÀ KHÔNG chứa "j&t"
            keywords = [k.strip() for k in filter_htgh.split(',') if k.strip()]
            include_kws = [k for k in keywords if not k.startswith('!')]
            exclude_kws = [k[1:] for k in keywords if k.startswith('!') and len(k) > 1]

            if include_kws:
                if len(include_kws) == 1:
                    domain += [('x_studio_htgh', 'ilike', include_kws[0])]
                else:
                    # OR giữa các keyword include
                    domain += ['|'] * (len(include_kws) - 1)
                    for kw in include_kws:
                        domain += [('x_studio_htgh', 'ilike', kw)]

            for kw in exclude_kws:
                domain += [('x_studio_htgh', 'not ilike', kw)]

        if filter_delivery_type and filter_delivery_type != 'all':
            domain += [('x_studio_delivery_type', '=', filter_delivery_type)]

        if filter_tag_ids:
            try:
                ids = [int(x.strip()) for x in str(filter_tag_ids).split(',') if x.strip()]
                if ids:
                    domain += [('tag_ids', 'in', ids)]
            except (ValueError, TypeError):
                pass

        return domain
