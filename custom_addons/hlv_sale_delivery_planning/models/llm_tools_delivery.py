# -*- coding: utf-8 -*-
"""
Delivery Planner — LLM Data Tools (read-only)
=============================================
Tập hợp các tool ``@llm_tool`` (data-only) cho AI Dispatcher trong floating
chat của Delivery Planner.

NGUYÊN TẮC:
- 100% read-only — KHÔNG có hành động ghi (assign shipper, đổi state…).
  AI chỉ gợi ý, thủ kho tự bấm.
- Tự nhận filter user đang xem Kanban qua ``dp_active_filter`` (cache theo
  user hiện tại) — bằng nhịp này AI không cần được ép data trong system
  prompt mà có thể tự query khi cần.
- Tránh trả response quá to: list_orders mặc định ``limit=30``, address /
  product list bị cắt ngắn.

Tất cả tool được gắn lên thread khi ``ensure_chat_thread`` chạy
(xem ``delivery_suggestion.py``).
"""
import json
import logging
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.llm_tool.decorators import llm_tool

_logger = logging.getLogger(__name__)

# ir.config_parameter key chứa snapshot filter hiện tại của user (JSON).
_FILTER_PARAM_PREFIX = 'hlv_dp.chat.filters.uid_'

# Whitelist filter keys hợp lệ truyền cho ``get_dashboard_data``.
_PASSTHROUGH_FILTERS = {
    'search_query', 'filter_warehouse_id',
    'filter_delivery_status', 'filter_stock_status',
    'filter_packing_status',
    'filter_date_from', 'filter_date_to',
    'filter_done_date_from', 'filter_done_date_to',
    'filter_po_date_from', 'filter_po_date_to', 'filter_po_status',
    'filter_saler_code', 'filter_htgh',
    'filter_delivery_type', 'filter_tag_ids',
    'show_completed', 'filter_need_transfer',
    'filter_new_orders', 'filter_print_status',
    'filter_shipper_received',
}


def _money(v):
    try:
        return f"{int(v or 0):,}".replace(',', '.')
    except Exception:
        return str(v)


class HlvDeliveryPlannerTools(models.AbstractModel):
    """Bộ tool LLM (read-only) cho Delivery Planner.

    Đặt trên một AbstractModel riêng, không trộn với ``hlv.delivery.suggestion``
    để tách rõ "logic chat / prompt builder" vs "data tools mà AI gọi".
    """
    _name = 'hlv.delivery.planner.tools'
    _description = 'HLV Delivery Planner — LLM Data Tools (read-only)'

    # ──────────────────────────────────────────────────────────────────
    # Cache filter từ Kanban (snoop FE → server)
    # ──────────────────────────────────────────────────────────────────
    @api.model
    def _filter_param_key(self, uid=None):
        return f"{_FILTER_PARAM_PREFIX}{uid or self.env.uid}"

    @api.model
    def set_user_dashboard_context(self, filters):
        """Lưu snapshot filter Kanban hiện tại của user vào ir.config_parameter.
        Gọi từ FE mỗi khi ``_buildFetchKwargs`` chạy (debounce ở client).
        """
        clean = {}
        for k, v in (filters or {}).items():
            if k in _PASSTHROUGH_FILTERS and v not in (None, '', 'all', False):
                clean[k] = v
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param(self._filter_param_key(), json.dumps(clean))
        return True

    @api.model
    def _get_user_dashboard_context(self):
        ICP = self.env['ir.config_parameter'].sudo()
        raw = ICP.get_param(self._filter_param_key(), '')
        if not raw:
            return {}
        try:
            return json.loads(raw) or {}
        except Exception:
            return {}

    # ──────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────
    def _service(self):
        return self.env['hlv.delivery.planner.service']

    def _resolve_warehouse_id(self, warehouse_name):
        """Cho phép AI truyền tên kho thay vì id."""
        if not warehouse_name:
            return None
        if isinstance(warehouse_name, int) or (
            isinstance(warehouse_name, str) and warehouse_name.isdigit()
        ):
            return int(warehouse_name)
        wh = self.env['stock.warehouse'].search(
            [('name', '=ilike', warehouse_name)], limit=1,
        )
        return wh.id if wh else None

    def _resolve_tag_ids(self, route_or_tag):
        if not route_or_tag:
            return ''
        if isinstance(route_or_tag, (list, tuple)):
            tokens = list(route_or_tag)
        else:
            tokens = [t.strip() for t in str(route_or_tag).split(',') if t.strip()]
        ids = []
        for tok in tokens:
            if tok.isdigit():
                ids.append(int(tok))
                continue
            tag = self.env['crm.tag'].search([('name', '=ilike', tok)], limit=1)
            if tag:
                ids.append(tag.id)
        return ','.join(str(i) for i in ids) if ids else ''

    def _build_kwargs(self, packing_status=None, warehouse_name=None,
                      route_or_tag=None, htgh=None, search=None,
                      use_active_filter=True, limit=30, offset=0):
        kwargs = {
            'limit': int(limit),
            'offset': int(offset),
            'include_stats': False,
        }
        if use_active_filter:
            kwargs.update(self._get_user_dashboard_context())
        if packing_status:
            kwargs['filter_packing_status'] = packing_status
        if warehouse_name:
            wh_id = self._resolve_warehouse_id(warehouse_name)
            if wh_id:
                kwargs['filter_warehouse_id'] = wh_id
        if route_or_tag:
            tag_ids = self._resolve_tag_ids(route_or_tag)
            if tag_ids:
                kwargs['filter_tag_ids'] = tag_ids
        if htgh:
            kwargs['filter_htgh'] = htgh
        if search:
            kwargs['search_query'] = search
        # Default an toàn: nếu chưa có status nào, tập trung "đã đóng, chờ giao"
        kwargs.setdefault('filter_packing_status', 'packed_waiting_ship')
        return kwargs

    # ──────────────────────────────────────────────────────────────────
    # TOOL 1 — Filter snapshot
    # ──────────────────────────────────────────────────────────────────
    @llm_tool(name='dp_active_filter', read_only_hint=True)
    def tool_active_filter(self) -> dict:
        """Trả về snapshot filter Kanban Delivery Planner mà user đang xem.

        Dùng khi user nói "trong filter của tao" / "đơn tao đang lọc". Các
        tool khác mặc định đã ăn filter này, nhưng có thể gọi tool này để
        xác nhận hoặc liệt kê lại các filter cho user.
        """
        df = self._get_user_dashboard_context()
        out = {'has_filter': bool(df), 'filters': {}}
        for k, v in df.items():
            label = v
            if k == 'filter_warehouse_id':
                wh = self.env['stock.warehouse'].browse(int(v))
                label = wh.name if wh.exists() else v
                out['filters']['warehouse'] = label
            elif k == 'filter_tag_ids':
                try:
                    ids = [int(x) for x in str(v).split(',') if x.strip()]
                    names = self.env['crm.tag'].browse(ids).mapped('name')
                    out['filters']['tags'] = names
                except Exception:
                    out['filters']['tags'] = v
            else:
                out['filters'][k] = v
        return out

    # ──────────────────────────────────────────────────────────────────
    # TOOL 2 — Dashboard summary (KPI)
    # ──────────────────────────────────────────────────────────────────
    @llm_tool(name='dp_dashboard_summary', read_only_hint=True)
    def tool_dashboard_summary(self, packing_status: str = '',
                               warehouse_name: str = '',
                               use_active_filter: bool = True) -> dict:
        """Tóm tắt KPI: tổng số đơn, tổng giá trị, phân bổ theo kho / tuyến.

        Args:
            packing_status: 'packed_waiting_ship' (mặc định nếu trống),
                'all', 'pending'... — bỏ trống = ưu tiên status từ active
                filter, fallback 'packed_waiting_ship'.
            warehouse_name: lọc theo tên kho (không phân biệt hoa thường).
            use_active_filter: True = áp filter user đang lọc trên Kanban.
        """
        kwargs = self._build_kwargs(
            packing_status=packing_status or None,
            warehouse_name=warehouse_name or None,
            use_active_filter=use_active_filter,
            limit=200, offset=0,
        )
        try:
            data = self._service().get_dashboard_data(**kwargs)
        except Exception as e:
            _logger.exception("dp_dashboard_summary failed")
            return {'error': str(e), 'orders': []}
        orders = data.get('orders') or []
        by_wh = defaultdict(lambda: {'count': 0, 'value': 0.0})
        by_route = defaultdict(lambda: {'count': 0, 'value': 0.0})
        total_value = 0.0
        for o in orders:
            v = o.get('amount_total') or 0.0
            total_value += v
            wh = o.get('warehouse_id')
            wh_name = wh[1] if isinstance(wh, (list, tuple)) and len(wh) > 1 else 'Khác'
            by_wh[wh_name]['count'] += 1
            by_wh[wh_name]['value'] += v
            tag_pairs = o.get('tag_ids') or []
            if not tag_pairs:
                by_route['(chưa phân tuyến)']['count'] += 1
                by_route['(chưa phân tuyến)']['value'] += v
            for t in tag_pairs:
                if isinstance(t, (list, tuple)) and len(t) > 1:
                    by_route[t[1]]['count'] += 1
                    by_route[t[1]]['value'] += v
        return {
            'total_orders': data.get('total_count') or len(orders),
            'sample_size': len(orders),
            'total_value': total_value,
            'total_value_str': _money(total_value),
            'by_warehouse': [
                {'warehouse': k, 'count': v['count'],
                 'value': v['value'], 'value_str': _money(v['value'])}
                for k, v in sorted(by_wh.items(), key=lambda kv: -kv[1]['count'])
            ],
            'by_route': [
                {'route': k, 'count': v['count'],
                 'value': v['value'], 'value_str': _money(v['value'])}
                for k, v in sorted(by_route.items(), key=lambda kv: -kv[1]['count'])
            ],
            'filter_applied': self._get_user_dashboard_context() if use_active_filter else {},
        }

    # ──────────────────────────────────────────────────────────────────
    # TOOL 3 — List orders (paginated)
    # ──────────────────────────────────────────────────────────────────
    @llm_tool(name='dp_list_orders', read_only_hint=True)
    def tool_list_orders(self, packing_status: str = '',
                         warehouse_name: str = '',
                         route_or_tag: str = '',
                         htgh: str = '',
                         search: str = '',
                         use_active_filter: bool = True,
                         limit: int = 20,
                         offset: int = 0) -> dict:
        """Liệt kê các đơn bán theo filter.

        Trả về 1 dict: {orders: [...], total, has_more}. Mỗi order chứa
        fields gọn: id, name, partner, address, route, htgh, amount,
        commitment_date, warehouse, shipper, product_count.

        Args:
            packing_status: ví dụ 'packed_waiting_ship', 'pending', 'all'.
            warehouse_name: tên kho (=ilike).
            route_or_tag: tên tag hoặc danh sách tag, phân tách dấu phẩy.
            htgh: lọc theo hình thức giao hàng.
            search: tìm theo tên KH, mã đơn, số điện thoại.
            use_active_filter: True = nối thêm filter user đang xem Kanban.
            limit: tối đa 100. Mặc định 30.
            offset: pagination.
        """
        limit = max(1, min(int(limit or 20), 50))
        kwargs = self._build_kwargs(
            packing_status=packing_status or None,
            warehouse_name=warehouse_name or None,
            route_or_tag=route_or_tag or None,
            htgh=htgh or None,
            search=search or None,
            use_active_filter=use_active_filter,
            limit=limit, offset=int(offset or 0),
        )
        try:
            data = self._service().get_dashboard_data(**kwargs)
        except Exception as e:
            _logger.exception("dp_list_orders failed")
            return {'error': str(e), 'orders': []}
        raw = data.get('orders') or []
        out = []
        for o in raw:
            wh = o.get('warehouse_id')
            wh_name = wh[1] if isinstance(wh, (list, tuple)) and len(wh) > 1 else ''
            tag_pairs = o.get('tag_ids') or []
            tags = [t[1] for t in tag_pairs if isinstance(t, (list, tuple)) and len(t) > 1]
            partner = o.get('partner_id')
            partner_name = partner[1] if isinstance(partner, (list, tuple)) and len(partner) > 1 else ''
            shipper = ''
            picking_names = []
            for p in (o.get('pickings') or []):
                picking_names.append(p.get('name') or '')
                su = p.get('shipper_user_id')
                if isinstance(su, (list, tuple)) and len(su) > 1 and not shipper:
                    shipper = su[1]
            address = (o.get('misa_shipping_address') or '').strip()
            if len(address) > 120:
                address = address[:117] + '...'
            out.append({
                'id': o.get('id'),
                'name': o.get('name'),
                'partner': partner_name,
                'address': address,
                'route': ' / '.join(tags),
                'htgh': o.get('x_studio_htgh') or '',
                'amount': o.get('amount_total') or 0.0,
                'amount_str': _money(o.get('amount_total') or 0),
                'commitment_date': o.get('commitment_date') or '',
                'warehouse': wh_name,
                'shipper': shipper,
                'pickings': [n for n in picking_names if n][:5],
            })
        total = data.get('total_count') or len(raw)
        return {
            'orders': out,
            'total': total,
            'returned': len(out),
            'offset': int(offset or 0),
            'has_more': (int(offset or 0) + len(out)) < total,
            'filter_applied': self._get_user_dashboard_context() if use_active_filter else {},
        }

    # ──────────────────────────────────────────────────────────────────
    # TOOL 4 — Order detail
    # ──────────────────────────────────────────────────────────────────
    @llm_tool(name='dp_order_detail', read_only_hint=True)
    def tool_order_detail(self, order_id_or_name: str) -> dict:
        """Chi tiết 1 đơn bán: products, address, pickings, shipper, PO.

        Args:
            order_id_or_name: id (số) hoặc mã đơn (vd 'S00123').
        """
        SO = self.env['sale.order']
        rec = SO.browse()
        if str(order_id_or_name).isdigit():
            rec = SO.browse(int(order_id_or_name)).exists()
        if not rec:
            rec = SO.search([('name', '=', str(order_id_or_name))], limit=1)
        if not rec:
            return {'error': f"Không tìm thấy đơn '{order_id_or_name}'"}

        partner = rec.partner_shipping_id or rec.partner_id
        lines = []
        for ml in rec.order_line:
            if ml.product_id.type == 'service':
                continue
            lines.append({
                'product': ml.product_id.display_name,
                'ordered': ml.product_uom_qty or 0,
                'delivered': ml.qty_delivered or 0,
                'pending': max((ml.product_uom_qty or 0) - (ml.qty_delivered or 0), 0),
                'uom': ml.product_uom.name if ml.product_uom else '',
            })
        pickings = []
        for p in rec.picking_ids:
            shipper = p.shipper_user_id.name if p.shipper_user_id else ''
            pickings.append({
                'name': p.name,
                'type': p.picking_type_id.name if p.picking_type_id else '',
                'state': p.state,
                'scheduled_date': fields.Datetime.to_string(p.scheduled_date) if p.scheduled_date else '',
                'date_done': fields.Datetime.to_string(p.date_done) if p.date_done else '',
                'shipper': shipper,
            })
        pos = []
        for po in rec.purchase_order_ids if hasattr(rec, 'purchase_order_ids') else []:
            pos.append({'name': po.name, 'state': po.state,
                        'date_planned': fields.Datetime.to_string(po.date_planned) if po.date_planned else ''})
        return {
            'id': rec.id,
            'name': rec.name,
            'state': rec.state,
            'partner': partner.display_name if partner else '',
            'partner_phone': (partner.phone or partner.mobile) if partner else '',
            'address': rec.misa_shipping_address or (
                ', '.join(p for p in [
                    partner.street, partner.street2, partner.city,
                    partner.state_id.name if partner and partner.state_id else None,
                ] if p) if partner else ''
            ),
            'warehouse': rec.warehouse_id.name if rec.warehouse_id else '',
            'route': ' / '.join(rec.tag_ids.mapped('name')),
            'htgh': rec.x_studio_htgh or '',
            'delivery_type': rec.x_studio_delivery_type or '',
            'commitment_date': fields.Datetime.to_string(rec.commitment_date) if rec.commitment_date else '',
            'amount_total': rec.amount_total,
            'amount_total_str': _money(rec.amount_total),
            'currency': rec.currency_id.name if rec.currency_id else 'VND',
            'note': rec.origin or '',
            'lines': lines,
            'pickings': pickings,
            'purchase_orders': pos,
        }

    # ──────────────────────────────────────────────────────────────────
    # TOOL 5 — List routes (active)
    # ──────────────────────────────────────────────────────────────────
    @llm_tool(name='dp_list_routes', read_only_hint=True)
    def tool_list_routes(self, packing_status: str = '',
                         warehouse_name: str = '',
                         use_active_filter: bool = True) -> dict:
        """Danh sách các tuyến (tag_ids) đang có đơn ở trạng thái lọc.

        Trả về list tuyến + số đơn + tổng giá trị, sort giảm dần theo count.
        """
        kwargs = self._build_kwargs(
            packing_status=packing_status or None,
            warehouse_name=warehouse_name or None,
            use_active_filter=use_active_filter,
            limit=200, offset=0,
        )
        try:
            data = self._service().get_dashboard_data(**kwargs)
        except Exception as e:
            _logger.exception("dp_list_routes failed")
            return {'error': str(e), 'routes': []}
        routes = defaultdict(lambda: {'count': 0, 'value': 0.0, 'orders': []})
        no_route_key = '(chưa phân tuyến)'
        for o in data.get('orders') or []:
            v = o.get('amount_total') or 0.0
            tag_pairs = o.get('tag_ids') or []
            keys = [t[1] for t in tag_pairs if isinstance(t, (list, tuple)) and len(t) > 1] or [no_route_key]
            for k in keys:
                routes[k]['count'] += 1
                routes[k]['value'] += v
                if len(routes[k]['orders']) < 8:
                    routes[k]['orders'].append(o.get('name'))
        return {
            'routes': [
                {'name': k, 'count': v['count'], 'value': v['value'],
                 'value_str': _money(v['value']), 'sample_orders': v['orders']}
                for k, v in sorted(routes.items(), key=lambda kv: -kv[1]['count'])
            ],
            'filter_applied': self._get_user_dashboard_context() if use_active_filter else {},
        }

    # ──────────────────────────────────────────────────────────────────
    # TOOL 6 — Shipper history
    # ──────────────────────────────────────────────────────────────────
    @llm_tool(name='dp_shipper_history', read_only_hint=True)
    def tool_shipper_history(self, days: int = 30,
                             shipper_name: str = '') -> dict:
        """Lịch sử shipper (read-only, để gợi ý — KHÔNG tự assign).

        Args:
            days: số ngày tra cứu (mặc định 30, max 180).
            shipper_name: nếu cung cấp, chỉ trả 1 shipper khớp tên.
        """
        days = max(1, min(int(days or 30), 180))
        date_from = fields.Datetime.now() - timedelta(days=days)
        domain = [
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', '=', 'done'),
            ('date_done', '>=', date_from),
            ('shipper_user_id', '!=', False),
        ]
        if shipper_name:
            user = self.env['res.users'].search(
                [('name', 'ilike', shipper_name)], limit=1,
            )
            if not user:
                return {'shippers': [], 'note': f'Không tìm thấy shipper "{shipper_name}"'}
            domain.append(('shipper_user_id', '=', user.id))
        pickings = self.env['stock.picking'].search(domain, limit=3000)

        agg = {}
        for p in pickings:
            su = p.shipper_user_id
            entry = agg.setdefault(su.id, {
                'name': su.name, 'completed_orders': 0,
                '_total_hours': 0.0, '_count_with_duration': 0,
                'avg_delivery_hours': None,
                'on_time_count': 0, 'late_count': 0,
                'routes': defaultdict(int),
            })
            entry['completed_orders'] += 1
            start = None
            for fld in ('shipper_received_date', 'shipper_received_at',
                        'date_pack', 'scheduled_date'):
                if fld in p._fields:
                    val = getattr(p, fld, None)
                    if val:
                        start = val
                        break
            if start and p.date_done:
                try:
                    h = (p.date_done - start).total_seconds() / 3600.0
                    if 0 < h < 240:
                        entry['_total_hours'] += h
                        entry['_count_with_duration'] += 1
                except Exception:
                    pass
            try:
                if p.scheduled_date and p.date_done:
                    if p.date_done > p.scheduled_date:
                        entry['late_count'] += 1
                    else:
                        entry['on_time_count'] += 1
            except Exception:
                pass
            try:
                so = p.sale_id
                if so:
                    for t in so.tag_ids:
                        entry['routes'][t.name] += 1
            except Exception:
                pass

        out = []
        for v in agg.values():
            if v['_count_with_duration']:
                v['avg_delivery_hours'] = round(v['_total_hours'] / v['_count_with_duration'], 2)
            on_total = v['on_time_count'] + v['late_count']
            out.append({
                'name': v['name'],
                'completed_orders': v['completed_orders'],
                'avg_delivery_hours': v['avg_delivery_hours'],
                'on_time_rate': round(100 * v['on_time_count'] / on_total) if on_total else None,
                'top_routes': dict(sorted(v['routes'].items(),
                                          key=lambda kv: -kv[1])[:8]),
            })
        out.sort(key=lambda x: -x['completed_orders'])
        return {'days': days, 'shippers': out}
