from odoo import models
from odoo.osv import expression
import pytz
from datetime import datetime, timedelta


class DeliveryPlannerServiceDomain(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    def _get_current_user_misa_codes(self):
        """Mã sale MISA mà CHÍNH tài khoản đang đăng nhập (self.env.user) được cấu hình xem trên
        trang /sale_plan (res.users.x_misa_saler_codes, field của module misa_invoice_status_report
        — dùng getattr vì hlv_sale_delivery_planning không depend cứng module đó, giống cách các
        module khác đọc field Studio x_studio_misa_saler_code)."""
        codes = []
        seen = set()
        for part in (getattr(self.env.user, 'x_misa_saler_codes', '') or '').split(','):
            code = part.strip()
            if code and code.upper() not in seen:
                seen.add(code.upper())
                codes.append(code)
        return codes

    def _get_mine_only_domain(self):
        """Domain cho filter "Đơn của tôi": đơn khớp 1 trong các mã sale MISA đã khai báo cho tài
        khoản đang đăng nhập, HOẶC (nếu tài khoản được đánh dấu x_handle_unassigned_saler_orders)
        đơn không có mã sale MISA nào (VD: đơn Shopee). Trả về None nếu tài khoản chưa được cấu
        hình gì cả — caller (_build_search_domain) coi None là "fail-closed" (trả về rỗng), KHÔNG
        phải "không giới hạn", vì mục đích filter này là tránh sale bấm nhầm đơn của người khác."""
        codes = self._get_current_user_misa_codes()
        handle_unassigned = bool(getattr(self.env.user, 'x_handle_unassigned_saler_orders', False))
        sub_domains = [
            ['|'] * (len(codes) - 1) + [('x_studio_misa_saler_code', '=ilike', c) for c in codes]
        ] if codes else []
        if handle_unassigned:
            sub_domains.append([('x_studio_misa_saler_code', '=', False)])
        if not sub_domains:
            return None
        return expression.OR(sub_domains)

    def _get_today_delivered_so_ids(self):
        """SO ID có ít nhất 1 phiếu OUT done trong NGÀY HÔM NAY (theo TZ user).

        Dùng để bypass SQL prefilter `delivery_status` (xem _build_search_domain),
        đảm bảo các SO đã giao trong ngày luôn xuất hiện trên dashboard kể cả
        khi user lọc "Chưa giao & Giao 1 phần".
        """
        user_tz_name = self.env.user.tz or 'UTC'
        try:
            user_tz = pytz.timezone(user_tz_name)
        except Exception:
            user_tz = pytz.UTC
        now_local = datetime.now(user_tz)
        start_local = user_tz.localize(datetime(now_local.year, now_local.month, now_local.day))
        end_local = start_local + timedelta(days=1)
        utc_from = start_local.astimezone(pytz.UTC).replace(tzinfo=None)
        utc_to = end_local.astimezone(pytz.UTC).replace(tzinfo=None)
        pickings = self.env['stock.picking'].sudo().search_read([
            ('state', '=', 'done'),
            ('date_done', '>=', utc_from),
            ('date_done', '<', utc_to),
            ('picking_type_code', '=', 'outgoing'),
            ('sale_id', '!=', False),
        ], ['sale_id'])
        return list({p['sale_id'][0] for p in pickings if p.get('sale_id')})

    def _build_search_domain(
        self, search_query, filter_warehouse_id,
        filter_delivery_status, filter_date_from, filter_date_to,
        filter_saler_code='', filter_htgh='', filter_delivery_type='all', filter_tag_ids='',
        filter_mine=False,
    ):
        """Xây dựng domain tìm kiếm Sale Order dựa trên các bộ lọc."""
        search_query = (search_query or '').strip()
        filter_saler_code = (filter_saler_code or '').strip()
        filter_htgh = (filter_htgh or '').strip()
        domain = [('state', 'in', ['sale', 'done'])]

        # Coarse SQL prefilter on native sale.order.delivery_status to slash the
        # candidate set BEFORE the heavier Python real_delivery_status pass in
        # _calculate_po_and_stock_status. Native values: pending / started /
        # partial / full. Real values: unshipped / partial / full. The mapping
        # below is a SAFE SUPERSET (we keep False/unset to avoid dropping
        # ambiguous orders), so the downstream Python filter still has the
        # final say. This typically cuts the scanned set by 50-80% on dashboards
        # heavily filtered to "pending/partial".
        _native_status_map = {
            'pending_partial': ('pending', 'started', 'partial', False),
            'unshipped':       ('pending', 'started', False),
            'pending':         ('pending', 'started', False),
            'partial':         ('partial', False),
            'full':            ('full',),
        }
        native_allowed = _native_status_map.get(filter_delivery_status)
        if native_allowed:
            # Bypass: đơn có phiếu OUT done trong NGÀY HÔM NAY luôn được include
            # (kể cả khi delivery_status='full' không nằm trong native_allowed).
            # Cần thiết vì cột "Đã giao trong ngày" phải hiển thị đầy đủ kể cả
            # user đang lọc "Chưa & Giao 1 phần".
            today_so_ids = self._get_today_delivered_so_ids()
            if today_so_ids:
                domain += ['|',
                           ('delivery_status', 'in', list(native_allowed)),
                           ('id', 'in', today_so_ids)]
            else:
                domain += [('delivery_status', 'in', list(native_allowed))]

        if filter_warehouse_id != 'all':
            domain += [('warehouse_id', '=', int(filter_warehouse_id))]

        if search_query:
            domain += ['|', '|', '|', '|',
                       ('name', 'ilike', search_query),
                       ('partner_id.name', 'ilike', search_query),
                       ('x_studio_tham_chiu_shopee', 'ilike', search_query),
                       ('order_line.product_id.name', 'ilike', search_query),
                       ('order_line.product_id.default_code', 'ilike', search_query)]

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

        if filter_mine:
            mine_domain = self._get_mine_only_domain()
            # Fail-closed: nếu tài khoản chưa được cấu hình mã sale MISA lẫn cờ
            # "xử lý đơn không có mã" thì KHÔNG được coi là "không giới hạn" —
            # mục đích của filter này là tránh sale bấm nhầm đơn của người khác,
            # nên khi thiếu cấu hình phải trả về rỗng, không phải trả về tất cả.
            domain += mine_domain if mine_domain is not None else [('id', '=', 0)]

        return domain
