"""Stats-only endpoint with in-memory cache and snapshot fast path.

Strategy: cache the heavy `_calculate_po_and_stock_status` output keyed by
(db, uid, filter signature). Frontend can call `get_dashboard_stats_only`
in parallel with the main data fetch so the KPI cards paint immediately
when the cache is warm. Cache invalidation is driven by a global version
counter that is bumped on bus notifications. When all candidate sale orders
have clean snapshots, this endpoint skips the heavy status pipeline entirely.
"""
import json
import threading
import time

from odoo import api, models

# Module-level cache shared per Odoo worker process.
# Multi-worker setups will warm independently; the short TTL + version bump
# from change hooks keeps staleness bounded.
_STATS_CACHE = {}                # {key: (timestamp, version, dashboard_stats, total_count)}
_STATS_CACHE_LOCK = threading.Lock()
_STATS_CACHE_TTL = 120           # seconds
_STATS_CACHE_MAX = 200
_STATS_CACHE_VERSION = {'v': 0}  # bumped to invalidate every entry


def bump_stats_cache_version():
    """Public helper: invalidate all cached stats (called by bus hooks)."""
    _STATS_CACHE_VERSION['v'] += 1


def _put(key, dashboard_stats, total_count):
    with _STATS_CACHE_LOCK:
        _STATS_CACHE[key] = (
            time.time(), _STATS_CACHE_VERSION['v'],
            dashboard_stats, total_count,
        )
        if len(_STATS_CACHE) > _STATS_CACHE_MAX:
            # Drop oldest 1/4
            drop = sorted(_STATS_CACHE.items(), key=lambda kv: kv[1][0])
            for k, _ in drop[: _STATS_CACHE_MAX // 4]:
                _STATS_CACHE.pop(k, None)


def _get(key):
    with _STATS_CACHE_LOCK:
        entry = _STATS_CACHE.get(key)
    if not entry:
        return None
    ts, ver, stats, total = entry
    if (time.time() - ts) >= _STATS_CACHE_TTL:
        return None
    if ver != _STATS_CACHE_VERSION['v']:
        return None
    return stats, total


class DeliveryPlannerServiceStats(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    def _build_stats_cache_key(self, **filters):
        key_data = {'db': self.env.cr.dbname, 'uid': self.env.uid}
        key_data.update(filters)
        return json.dumps(key_data, sort_keys=True, default=str)

    def _store_stats_cache(self, dashboard_stats, total_count, **filters):
        """Called from get_dashboard_data so subsequent stats-only calls are warm."""
        try:
            key = self._build_stats_cache_key(**filters)
            _put(key, dashboard_stats, total_count)
        except Exception:
            pass

    @api.model
    def get_dashboard_stats_only(
        self,
        search_query='', filter_warehouse_id='all',
        filter_delivery_status='all', filter_stock_status='all',
        filter_packing_status='all', filter_date_from='', filter_date_to='',
        filter_po_date_from='', filter_po_date_to='', filter_po_status='all',
        filter_done_date_from='', filter_done_date_to='',
        filter_saler_code='', filter_htgh='', filter_delivery_type='all',
        filter_tag_ids='', show_completed=False,
        filter_need_transfer=False, filter_new_orders=False,
        filter_print_status='all', filter_shipper_received='all',
        domain=None,
    ):
        """Return ONLY {dashboard_stats, total_count, cached}.

        Hits the in-memory cache when warm (~ms response). On miss, computes
        the same status pipeline as `get_dashboard_data` but skips all
        formatting / attachment / package / flow work.
        """
        filters = dict(
            search_query=search_query, filter_warehouse_id=filter_warehouse_id,
            filter_delivery_status=filter_delivery_status,
            filter_stock_status=filter_stock_status,
            filter_packing_status=filter_packing_status,
            filter_date_from=filter_date_from, filter_date_to=filter_date_to,
            filter_po_date_from=filter_po_date_from,
            filter_po_date_to=filter_po_date_to,
            filter_po_status=filter_po_status,
            filter_done_date_from=filter_done_date_from,
            filter_done_date_to=filter_done_date_to,
            filter_saler_code=filter_saler_code, filter_htgh=filter_htgh,
            filter_delivery_type=filter_delivery_type,
            filter_tag_ids=filter_tag_ids,
            show_completed=show_completed,
            filter_need_transfer=filter_need_transfer,
            filter_new_orders=filter_new_orders,
            filter_print_status=filter_print_status,
            filter_shipper_received=filter_shipper_received,
            domain=domain,
        )
        key = self._build_stats_cache_key(**filters)
        cached = _get(key)
        if cached is not None:
            stats, total = cached
            return {'dashboard_stats': stats, 'total_count': total, 'cached': True}

        # Cold compute
        search_domain = self._build_search_domain(
            search_query, filter_warehouse_id,
            filter_delivery_status, filter_date_from, filter_date_to,
            filter_saler_code=filter_saler_code,
            filter_htgh=filter_htgh,
            filter_delivery_type=filter_delivery_type,
            filter_tag_ids=filter_tag_ids,
        )
        if domain:
            search_domain = search_domain + list(domain)
        sales = self.env['sale.order'].search(search_domain)

        if self._can_use_snapshot_dashboard_match(
            filter_po_date_from=filter_po_date_from,
            filter_po_date_to=filter_po_date_to,
            filter_po_status=filter_po_status,
            filter_done_date_from=filter_done_date_from,
            filter_done_date_to=filter_done_date_to,
            filter_need_transfer=filter_need_transfer,
            domain=domain,
        ):
            snapshot_match = self._get_snapshot_dashboard_match(
                sales,
                filter_delivery_status=filter_delivery_status,
                filter_stock_status=filter_stock_status,
                filter_packing_status=filter_packing_status,
                show_completed=show_completed,
                filter_new_orders=filter_new_orders,
                filter_print_status=filter_print_status,
                filter_shipper_received=filter_shipper_received,
            )
            if snapshot_match:
                dashboard_stats = snapshot_match['dashboard_stats']
                total_count = len(snapshot_match['matched_ids'])
                _put(key, dashboard_stats, total_count)
                return {
                    'dashboard_stats': dashboard_stats,
                    'total_count': total_count,
                    'cached': False,
                    'source': 'snapshot',
                }

        _, matched_ids, dashboard_stats, _, _, _ = self._calculate_po_and_stock_status(
            sales, filter_po_date_from, filter_po_date_to,
            filter_po_status, filter_delivery_status,
            filter_stock_status, filter_packing_status,
            show_completed=show_completed,
            filter_need_transfer=filter_need_transfer,
            filter_new_orders=filter_new_orders,
            filter_done_date_from=filter_done_date_from,
            filter_done_date_to=filter_done_date_to,
            filter_print_status=filter_print_status,
            filter_shipper_received=filter_shipper_received,
        )
        total_count = len(matched_ids)
        _put(key, dashboard_stats, total_count)
        return {'dashboard_stats': dashboard_stats, 'total_count': total_count, 'cached': False}
