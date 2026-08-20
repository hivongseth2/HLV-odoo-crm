"""Snapshot-backed dashboard query helpers.

This file keeps the optional fast path for the delivery planner dashboard:
when all candidate sale orders have a clean snapshot, list/count/KPI filters
use the snapshot table and the service computes realtime stock data only for
the visible page. If the snapshot is incomplete or dirty, callers fall back to
the existing full realtime pipeline.
"""

from odoo import api, models

from ..models.delivery_planner_snapshot import SNAPSHOT_LOGIC_VERSION


class DeliveryPlannerServiceSnapshotQuery(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    @api.model
    def _get_snapshot_dashboard_match(
        self, sales, filter_delivery_status='all', filter_stock_status='all',
        filter_packing_status='all', show_completed=False,
        filter_new_orders=False, filter_print_status='all',
        filter_shipper_received='all',
    ):
        if not sales:
            return None

        snapshot_model = self.env['hlv.delivery.planner.snapshot'].sudo()
        snapshots = snapshot_model.search([('sale_order_id', 'in', sales.ids)])
        if len(snapshots) != len(sales):
            return None
        # KHÔNG còn yêu cầu snapshot_date == today: dirty=True giờ được invalidate đúng lúc
        # bởi hook trên sale/picking/move (đơn của chính nó) VÀ hook theo sản phẩm khi tồn
        # kho đổi do BẤT KỲ đơn nào khác (xem stock_move.py) — nên dirty=False là đủ tin,
        # không cần ép tính lại toàn bộ mỗi ngày (điều mà cron không bao giờ bắt kịp nổi với
        # ~24k snapshot). Chỉ has_delivered_today mới thực sự phụ thuộc lịch, được cron
        # _expire_delivered_today_flags() xử lý riêng, không cần snapshot_date ở đây.
        if any(
            snap.dirty or snap.logic_version != SNAPSHOT_LOGIC_VERSION
            for snap in snapshots
        ):
            return None

        sale_order_pos = {so_id: idx for idx, so_id in enumerate(sales.ids)}
        matched = snapshots.filtered(lambda snap: self._snapshot_matches_filters(
            snap,
            filter_delivery_status=filter_delivery_status,
            filter_stock_status=filter_stock_status,
            filter_packing_status=filter_packing_status,
            show_completed=show_completed,
            filter_new_orders=filter_new_orders,
            filter_print_status=filter_print_status,
            filter_shipper_received=filter_shipper_received,
        ))
        matched = matched.sorted(lambda snap: sale_order_pos.get(snap.sale_order_id.id, 0))
        matched_ids = matched.mapped('sale_order_id').ids
        return {
            'matched_ids': matched_ids,
            'dashboard_stats': self._snapshot_dashboard_stats(matched),
            'status_by_so': {
                snap.sale_order_id.id: self._snapshot_status_dict(snap)
                for snap in matched
            },
        }

    @api.model
    def _snapshot_matches_filters(
        self, snap, filter_delivery_status='all', filter_stock_status='all',
        filter_packing_status='all', show_completed=False,
        filter_new_orders=False, filter_print_status='all',
        filter_shipper_received='all',
    ):
        if not show_completed and snap.real_delivery_status == 'full' and not snap.has_delivered_today:
            return False
        if snap.has_delivered_today:
            return True

        if filter_delivery_status == 'pending_partial':
            delivery_ok = snap.real_delivery_status in ('unshipped', 'partial')
        elif filter_delivery_status in ('unshipped', 'pending'):
            delivery_ok = snap.real_delivery_status == 'unshipped'
        elif filter_delivery_status in ('partial', 'full'):
            delivery_ok = snap.real_delivery_status == filter_delivery_status
        else:
            delivery_ok = True

        effective_packing = self._snapshot_effective_packing(snap)
        if filter_packing_status in ('printed_waiting', 'packed_waiting_ship', 'shipping', 'delivered_today'):
            packing_ok = effective_packing == filter_packing_status
        else:
            packing_ok = filter_packing_status == 'all' or snap.packing_status == filter_packing_status

        if filter_stock_status != 'all' and snap.stock_status != filter_stock_status:
            return False

        if filter_print_status == 'has_unprinted':
            print_ok = bool(snap.has_assigned_pick) and not snap.has_active_pick_printed
        elif filter_print_status == 'all_printed':
            print_ok = bool(snap.has_assigned_pick) and snap.has_active_pick_printed
        else:
            print_ok = True

        if filter_shipper_received == 'received':
            shipper_ok = snap.has_shipper_received
        elif filter_shipper_received == 'not_received':
            shipper_ok = not snap.has_shipper_received
        else:
            shipper_ok = True

        if filter_new_orders and not snap.is_new_order:
            return False
        return delivery_ok and packing_ok and print_ok and shipper_ok

    @api.model
    def _snapshot_effective_packing(self, snap):
        if snap.has_delivered_today and (
            snap.real_delivery_status == 'full' or not snap.has_assigned_pick
        ):
            return 'delivered_today'
        if snap.has_shipper_received:
            return 'shipping'
        if snap.packing_status == 'fully_packed':
            return 'packed_waiting_ship'
        if snap.has_active_pick_printed and snap.packing_status != 'delivered':
            return 'printed_waiting'
        return snap.packing_status

    @api.model
    def _snapshot_dashboard_stats(self, snapshots):
        stats = {
            'total': 0, 'ready': 0, 'partial': 0, 'out_of_stock': 0,
            'packing_fully': 0, 'packing_partial': 0,
            'packing_unpacked': 0, 'packing_waiting': 0,
        }
        for snap in snapshots:
            stats['total'] += 1
            if snap.stock_status == 'ready':
                stats['ready'] += 1
            elif snap.stock_status == 'partial_ready':
                stats['partial'] += 1
            elif snap.stock_status == 'out_of_stock':
                stats['out_of_stock'] += 1
            if snap.real_delivery_status != 'full':
                if snap.packing_status == 'fully_packed':
                    stats['packing_fully'] += 1
                elif snap.packing_status == 'unpacked':
                    stats['packing_unpacked'] += 1
                elif snap.packing_status == 'waiting_stock':
                    stats['packing_waiting'] += 1
        return stats

    @api.model
    def _snapshot_status_dict(self, snap):
        return {
            'stock_status': snap.stock_status,
            'packing_status': snap.packing_status,
            'real_delivery_status': snap.real_delivery_status,
            'is_returned_or_stopped': snap.is_returned_or_stopped,
            'has_active_pick_printed': snap.has_active_pick_printed,
            'has_shipper_received': snap.has_shipper_received,
            'has_delivered_today': snap.has_delivered_today,
            'has_assigned_pick': snap.has_assigned_pick,
        }
