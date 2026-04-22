# -*- coding: utf-8 -*-
"""
Delivery Suggestion AI Helper
=============================
Cung cấp các method backend gom dữ liệu bối cảnh phục vụ AI Assistant
trong floating chat của Delivery Planner.

KHÔNG đụng tới logic / file gốc của module — chỉ thêm 1 model mới cho
phần "gợi ý" (skills).

Skills hiện có:
1. ``get_delivery_suggestion_context()`` — Gợi ý giao hàng dựa vào:
   - Các đơn ĐÃ ĐÓNG, CHỜ NHẬN GIAO (``packing_status='packed_waiting_ship'``)
   - Tuyến / địa chỉ giao (``misa_shipping_address``)
   - Giá trị đơn, sản phẩm
   - Lịch sử hoàn thành theo tài xế (shipper) trong N ngày gần nhất
2. (placeholder) ``get_purchase_suggestion_context()`` — gợi ý đi đơn mua,
   sẽ implement sau theo yêu cầu của user.
"""
import logging
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class HlvDeliverySuggestion(models.AbstractModel):
    _name = 'hlv.delivery.suggestion'
    _description = 'HLV Delivery Planner — AI Suggestion Context Builder'

    # ────────────────────────────────────────────────────────────────────
    # SKILL 2: Gợi ý giao hàng
    # ────────────────────────────────────────────────────────────────────
    @api.model
    def get_delivery_suggestion_context(self, sale_order_ids=None,
                                        warehouse_id=None, history_days=30,
                                        max_orders=80):
        """Gom dữ liệu cho prompt "gợi ý giao hàng".

        :param sale_order_ids: list[int] | None — nếu user chọn subset thì truyền
            vào, không thì lấy toàn bộ SO đang ở trạng thái "packed_waiting_ship"
            (đã đóng, chờ nhận giao).
        :param warehouse_id: int | None — lọc theo kho (tuỳ chọn).
        :param history_days: int — số ngày lùi lại để tính lịch sử shipper.
        :param max_orders: int — giới hạn số đơn để tránh prompt quá dài.

        :returns: dict gồm:
            - generated_at, warehouse, history_days, total_orders
            - orders: [ {id, name, partner, address, route, amount, scheduled_date,
                         shipper_user, shipper_name, products, pickings, ...} ]
            - shipper_history: { shipper_user_id: { name, completed_orders,
                                 avg_delivery_hours, routes:{route: count} } }
        """
        # 1) Tìm các SO có phiếu OUT đã đóng (state=assigned, x_printed=True)
        #    nhưng shipper chưa nhận → đây chính là cột "ĐÃ ĐÓNG, CHỜ NHẬN GIAO".
        Picking = self.env['stock.picking']
        picking_domain = [
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', '=', 'assigned'),
            ('x_printed', '=', True),
            ('shipper_received', '=', False),
        ]
        if warehouse_id:
            picking_domain.append(('picking_type_id.warehouse_id', '=', warehouse_id))
        if sale_order_ids:
            picking_domain.append(('sale_id', 'in', list(sale_order_ids)))

        pickings = Picking.search(picking_domain, limit=max_orders * 5)
        sale_orders = pickings.mapped('sale_id')
        if sale_order_ids:
            # Đảm bảo đúng tập user chọn (kể cả SO không có phiếu match)
            sale_orders |= self.env['sale.order'].browse(sale_order_ids).exists()
        sale_orders = sale_orders[:max_orders]

        # 2) Build orders payload
        orders_payload = []
        route_counter = defaultdict(int)
        route_value = defaultdict(float)

        for so in sale_orders:
            so_pickings = pickings.filtered(lambda p, sid=so.id: p.sale_id.id == sid)
            partner = so.partner_shipping_id or so.partner_id

            address = ''
            try:
                address = so.misa_shipping_address or ''
            except Exception:
                address = ''
            if not address and partner:
                parts = [
                    partner.street, partner.street2, partner.city,
                    partner.state_id.name if partner.state_id else None,
                    partner.country_id.name if partner.country_id else None,
                ]
                address = ', '.join([p for p in parts if p])

            # Tuyến: lấy từ tag (tuyến thường được tag), fallback theo
            # city/state để AI có manh mối phân tuyến.
            route_tags = []
            try:
                route_tags = [t.name for t in so.tag_ids]
            except Exception:
                route_tags = []
            route_label = ', '.join(route_tags) if route_tags else (
                (partner.city or '') + (
                    (' / ' + partner.state_id.name) if partner and partner.state_id else ''
                )
            )

            # HTGH (hãng vận chuyển) lấy từ free text (nếu có)
            htgh = ''
            for fld in ('x_htgh', 'x_studio_hinh_th_c_giao_hang', 'misa_htgh', 'note'):
                if fld in so._fields:
                    val = getattr(so, fld, None)
                    if val:
                        htgh = str(val)[:120]
                        break

            # Shipper hiện tại (nếu có ai đã được gán)
            shipper = so_pickings.mapped('shipper_user_id')[:1]

            # Sản phẩm
            products = []
            for ml in so_pickings.mapped('move_ids'):
                if ml.state in ('done', 'cancel'):
                    continue
                products.append({
                    'name': ml.product_id.display_name,
                    'qty': ml.product_uom_qty,
                    'uom': ml.product_uom.name if ml.product_uom else '',
                })

            # Ngày hẹn giao: ưu tiên commitment_date > scheduled (picking)
            commitment = so.commitment_date or False
            sched = min(so_pickings.mapped('scheduled_date'), default=False)

            order_dict = {
                'id': so.id,
                'name': so.name,
                'partner_id': partner.id if partner else False,
                'partner_name': partner.display_name if partner else '',
                'partner_phone': (partner.phone or partner.mobile or '') if partner else '',
                'address': address,
                'route': route_label,
                'tags': route_tags,
                'htgh': htgh,
                'amount_total': so.amount_total,
                'currency': so.currency_id.name if so.currency_id else 'VND',
                'commitment_date': str(commitment) if commitment else '',
                'scheduled_date': str(sched) if sched else '',
                'warehouse': so_pickings.mapped('picking_type_id.warehouse_id')[:1].name or '',
                'shipper_user_id': shipper.id if shipper else False,
                'shipper_name': shipper.name if shipper else '',
                'product_count': len(products),
                'products': products[:25],  # cap
                'picking_names': so_pickings.mapped('name'),
            }
            orders_payload.append(order_dict)

            if route_label:
                route_counter[route_label] += 1
                route_value[route_label] += so.amount_total or 0.0

        # 3) Lịch sử shipper (N ngày gần nhất) — học thời gian hoàn thành
        date_from = fields.Datetime.now() - timedelta(days=history_days)
        hist_pickings = Picking.search([
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', '=', 'done'),
            ('date_done', '>=', date_from),
            ('shipper_user_id', '!=', False),
        ], limit=2000)

        shipper_history = {}
        for p in hist_pickings:
            su = p.shipper_user_id
            if not su:
                continue
            entry = shipper_history.setdefault(su.id, {
                'shipper_user_id': su.id,
                'name': su.name,
                'completed_orders': 0,
                '_total_hours': 0.0,
                '_count_with_duration': 0,
                'avg_delivery_hours': None,
                'routes': defaultdict(int),
                'late_count': 0,
                'on_time_count': 0,
            })
            entry['completed_orders'] += 1

            # Tính giờ giao thực tế: từ lúc shipper nhận (shipper_received_date
            # nếu có) đến date_done. Nếu không có field, dùng scheduled_date.
            start = None
            for fld in ('shipper_received_date', 'shipper_received_at', 'date_pack', 'scheduled_date'):
                if fld in p._fields:
                    val = getattr(p, fld, None)
                    if val:
                        start = val
                        break
            if start and p.date_done:
                try:
                    delta = p.date_done - start
                    hours = delta.total_seconds() / 3600.0
                    if 0 < hours < 240:  # bỏ outlier
                        entry['_total_hours'] += hours
                        entry['_count_with_duration'] += 1
                except Exception:
                    pass

            # Late vs on-time so với scheduled
            try:
                if p.scheduled_date and p.date_done:
                    if p.date_done > p.scheduled_date:
                        entry['late_count'] += 1
                    else:
                        entry['on_time_count'] += 1
            except Exception:
                pass

            # Route history (qua tag SO)
            try:
                so = p.sale_id
                if so:
                    for t in so.tag_ids:
                        entry['routes'][t.name] += 1
            except Exception:
                pass

        # Finalize shipper history
        for k, v in shipper_history.items():
            if v['_count_with_duration']:
                v['avg_delivery_hours'] = round(
                    v['_total_hours'] / v['_count_with_duration'], 2,
                )
            v['routes'] = dict(sorted(
                v['routes'].items(), key=lambda kv: kv[1], reverse=True
            )[:8])
            v.pop('_total_hours', None)
            v.pop('_count_with_duration', None)

        # 4) Route summary
        route_summary = []
        for r, cnt in sorted(route_counter.items(), key=lambda kv: kv[1], reverse=True):
            route_summary.append({
                'route': r,
                'order_count': cnt,
                'total_value': round(route_value[r], 0),
            })

        return {
            'generated_at': fields.Datetime.now().isoformat(),
            'warehouse_id': warehouse_id,
            'history_days': history_days,
            'total_orders': len(orders_payload),
            'orders': orders_payload,
            'route_summary': route_summary,
            'shipper_history': list(shipper_history.values()),
        }

    # ────────────────────────────────────────────────────────────────────
    # SKILL 1 (placeholder): Gợi ý đi đơn mua
    # ────────────────────────────────────────────────────────────────────
    @api.model
    def get_purchase_suggestion_context(self):
        """Sẽ implement sau khi có yêu cầu chi tiết."""
        return {
            'generated_at': fields.Datetime.now().isoformat(),
            'note': 'Chưa triển khai. Hãy hỏi nghiệp vụ rồi quay lại.',
        }
