/** @odoo-module **/

export class DeliveryPlannerDataMixin {
    async _silentRefresh() {
        const isKanban = this.state.viewMode === 'kanban';
        // Stats refreshed independently \u2014 don't block silent refresh on it
        this._fetchStatsAsync();
        try {
            const result = await this.orm.call(
                "sale.order",
                "get_delivery_dashboard_data",
                [],
                {
                    ...this._buildFetchKwargs(),
                    limit: isKanban ? this.state.kanbanBatchSize : this.state.itemsPerPage,
                    offset: isKanban ? 0 : (this.state.currentPage - 1) * this.state.itemsPerPage,
                    include_stats: false,
                }
            );
            this._mergeResult(result);
            await this._saveToCache(result);
        } catch (error) {
            console.error("Silent refresh failed:", error);
        }
    }

    /**
     * Smart merge: update existing orders in-place, add new, remove deleted.
     * OWL only re-renders cards whose reactive properties actually changed.
     */
    _mergeResult(result) {
        // Stats handled independently — only update if backend returned them
        if (result.dashboard_stats) {
            this.state.dashboardStats = result.dashboard_stats;
        }
        this.state.totalCount = result.total_count || 0;

        const newOrders = result.orders || [];
        const todayStr = new Date().toISOString().slice(0, 10);

        // Build map of current orders by ID for O(1) lookup
        const oldMap = new Map();
        for (const so of this.state.saleOrders) {
            oldMap.set(so.id, so);
        }

        // Build new order list, reusing old objects where nothing changed
        const merged = [];
        for (const fresh of newOrders) {
            fresh.flows = fresh.flows || [];
            fresh.pickings = fresh.pickings || [];
            fresh.lines = fresh.lines || [];
            fresh.pos = fresh.pos || [];
            const orderDate = fresh.misa_order_date || (fresh.date_order ? fresh.date_order.substring(0, 10) : '');
            fresh.is_new_order = orderDate === todayStr;

            const old = oldMap.get(fresh.id);
            if (old) {
                // Update existing order in-place (OWL detects property changes)
                const skipKeys = new Set(['id']);
                for (const key of Object.keys(fresh)) {
                    if (skipKeys.has(key)) continue;
                    old[key] = fresh[key];
                }
                // Re-apply flow link colors
                this._applyFlowColors(old);
                merged.push(old);
                oldMap.delete(fresh.id);
            } else {
                // New order
                this._applyFlowColors(fresh);
                merged.push(fresh);
            }
        }

        // Replace array only if order IDs changed (added/removed/reordered)
        const oldIds = this.state.saleOrders.map(o => o.id).join(',');
        const newIds = merged.map(o => o.id).join(',');
        if (oldIds !== newIds) {
            this.state.saleOrders = merged;
        }

        // Update warehouses/tags if first time
        if (this.state.warehouses.length === 0) {
            this.state.warehouses = result.warehouses || [];
        }
        if (this.state.tags.length === 0) {
            this.state.tags = result.tags || [];
        }
    }

    _applyFlowColors(so) {
        const nodeByName = {};
        so.flows.forEach(flow => {
            (flow.nodes || []).forEach(node => { nodeByName[node.name] = node; });
        });
        const colorClasses = ['info', 'warning', 'danger', 'primary', 'success', 'dark'];
        let colorIdx = 0;
        so.flows.forEach(flow => {
            (flow.nodes || []).forEach(node => {
                const parentName = node.return_of || node.backorder_of;
                if (parentName && nodeByName[parentName]) {
                    const parentNode = nodeByName[parentName];
                    node.parent_seq = parentNode.global_seq;
                    if (!parentNode.link_color) {
                        parentNode.link_color = colorClasses[colorIdx % colorClasses.length];
                        colorIdx++;
                    }
                    node.link_color = parentNode.link_color;
                }
            });
        });
    }


    // --- IndexedDB Cache helpers ---
    _CACHE_DB = 'hlv_dp_cache';
    _CACHE_STORE = 'dashboard';
    _CACHE_TTL = 5 * 60 * 1000; // 5 minutes
    _applyResult(result) {
        // NOTE: do not overwrite dashboardStats here — stats are loaded
        // independently via _fetchStatsAsync so the kanban/table can render
        // without waiting on stats compute. We only assign if the backend
        // actually returned non-null stats (legacy callers / first paint).
        if (result.dashboard_stats) {
            this.state.dashboardStats = result.dashboard_stats;
        }
        const fetchedOrders = result.orders || [];
        this.state.saleOrders = fetchedOrders.map(so => {
            so.flows = so.flows || [];
            so.pickings = so.pickings || [];
            so.lines = so.lines || [];
            so.pos = so.pos || [];
            this._applyFlowColors(so);
            return so;
        });

        // Đánh dấu đơn mới: misa_order_date (hoặc date_order) = hôm nay
        const todayStr = new Date().toISOString().slice(0, 10);
        for (const so of this.state.saleOrders) {
            const orderDate = so.misa_order_date || (so.date_order ? so.date_order.substring(0, 10) : '');
            so.is_new_order = orderDate === todayStr;
        }

        this.state.totalCount = result.total_count || 0;
        if (this.state.warehouses.length === 0) {
            this.state.warehouses = result.warehouses || [];
        }
        if (this.state.tags.length === 0) {
            this.state.tags = result.tags || [];
        }
    }

    /**
     * Build the kwargs object passed to RPC calls.
     * Shared by full data fetch and stats-only prefetch.
     */
    _buildFetchKwargs() {
        return {
            search_query: this.state.searchQuery.trim(),
            filter_warehouse_id: this.state.filterWarehouseId,
            filter_delivery_status: this.state.filterDeliveryStatus,
            filter_stock_status: this.state.filterStockStatus,
            filter_date_from: this.state.filterDateFrom,
            filter_date_to: this.state.filterDateTo,
            filter_done_date_from: this.state.filterDoneDateFrom,
            filter_done_date_to: this.state.filterDoneDateTo,
            filter_po_date_from: this.state.filterPODateFrom,
            filter_po_date_to: this.state.filterPODateTo,
            filter_po_status: this.state.filterPOStatus,
            filter_packing_status: this.state.filterPackingStatus,
            filter_saler_code: this.state.filterSalerCode.trim(),
            filter_htgh: this.state.filterHtgh.trim(),
            filter_delivery_type: this.state.filterDeliveryType,
            filter_tag_ids: this.state.filterTagIds.join(','),
            show_completed: this.state.showCompleted,
            filter_need_transfer: this.state.filterNeedTransfer,
            filter_new_orders: this.state.filterNewOrders,
            filter_print_status: this.state.filterPrintStatus,
            filter_shipper_received: this.state.filterShipperReceived,
        };
    }

    /**
     * Fetch KPI stats independently of the main data fetch. Runs in the
     * background and updates `state.dashboardStats` whenever it returns —
     * the table/kanban/card view never waits on it. Cached on backend so
     * cost is ~ms when warm.
     */
    async _fetchStatsAsync() {
        const myToken = (this._statsRequestSeq = (this._statsRequestSeq || 0) + 1);
        this.state.statsLoading = true;
        try {
            const stats = await this.orm.call(
                "sale.order",
                "get_delivery_dashboard_stats",
                [],
                this._buildFetchKwargs(),
            );
            // Drop stale responses if a newer request superseded this one
            if (myToken !== this._statsRequestSeq) return;
            if (stats && stats.dashboard_stats) {
                this.state.dashboardStats = stats.dashboard_stats;
                if (typeof stats.total_count === 'number') {
                    // Only update totalCount from stats if main fetch hasn't
                    // already populated it (avoid flicker).
                    if (!this.state.totalCount) {
                        this.state.totalCount = stats.total_count;
                    }
                }
            }
        } catch (e) {
            console.debug('[DP Stats] async fetch failed:', e);
        } finally {
            if (myToken === this._statsRequestSeq) {
                this.state.statsLoading = false;
            }
        }
    }

    async fetchData() {
        // Don't show full loading spinner if we already have data on screen
        // (cache restored OR previous fetch already populated saleOrders).
        // This prevents the full-screen overlay from flashing on every
        // filter change — instead the user keeps seeing the current rows
        // while a thin "refreshing" indicator runs at the top.
        const hasDataOnScreen = this._isCacheRestored || (this.state.saleOrders && this.state.saleOrders.length > 0);
        if (!hasDataOnScreen) {
            this.state.isLoading = true;
        } else {
            this.state.isRefreshing = true;
        }
        const isKanban = this.state.viewMode === 'kanban';

        // Fire stats fetch INDEPENDENTLY — we don't await it. Stats render
        // when ready, and never block kanban/table painting.
        this._fetchStatsAsync();

        try {
            const result = await this.orm.call(
                "sale.order",
                "get_delivery_dashboard_data",
                [],
                {
                    ...this._buildFetchKwargs(),
                    // Kanban tải theo batch, không phân trang backend
                    limit: isKanban ? this.state.kanbanBatchSize : this.state.itemsPerPage,
                    offset: isKanban ? 0 : (this.state.currentPage - 1) * this.state.itemsPerPage,
                    include_stats: false,
                }
            );

            this._applyResult(result);
            // Save to IndexedDB cache for instant restore on next page load
            await this._saveToCache(result);
            // Auto-load all remaining orders in background — no spinner, no confirm.
            // Ensures không xót đơn khi tổng số đơn > initial batch size.
            const remaining = (this.state.totalCount || 0) - this.state.saleOrders.length;
            if (remaining > 0 && remaining <= 50) {
                this._autoLoadAllRemaining(); // intentionally NOT awaited
            }
        } catch (error) {
            console.error("Lỗi khi tải dữ liệu bảng điều phối:", error);
        } finally {
            this.state.isLoading = false;
            this.state.isRefreshing = false;
        }
    }

    // --- Background auto-load (no-spinner, no confirm) ---
    /**
     * Tải hết toàn bộ đơn còn lại vào state.saleOrders trong nền,
     * ngay sau khi fetchData xong batch đầu.
     * - Không cần user bấm nút "Tải hết" nữa.
     * - Sequence token tự hủy load cũ khi filter thay đổi (tránh race condition).
     * - Chỉ dùng cho internal dashboard (không public web).
     */
    async _autoLoadAllRemaining() {
        const mySeq = ++this._autoLoadSeq;
        // Đợi 1 tick để render ban đầu hoàn thành trước
        await new Promise(r => setTimeout(r, 50));
        if (mySeq !== this._autoLoadSeq) return;

        const remaining = (this.state.totalCount || 0) - this.state.saleOrders.length;
        if (remaining <= 0) return;

        this.state.isLoadingMore = true;
        try {
            const offset = this.state.saleOrders.length;
            const result = await this.orm.call(
                "sale.order",
                "get_delivery_dashboard_data",
                [],
                {
                    ...this._buildFetchKwargs(),
                    limit: remaining,
                    offset: offset,
                    include_stats: false,
                }
            );
            if (mySeq !== this._autoLoadSeq) return; // stale — filter đổi trong lúc đang tải

            const fresh = (result && result.orders) || [];
            const todayStr = new Date().toISOString().slice(0, 10);
            const existingIds = new Set(this.state.saleOrders.map(o => o.id));
            for (const so of fresh) {
                if (existingIds.has(so.id)) continue;
                so.flows = so.flows || [];
                so.pickings = so.pickings || [];
                so.lines = so.lines || [];
                so.pos = so.pos || [];
                this._applyFlowColors(so);
                const orderDate = so.misa_order_date || (so.date_order ? so.date_order.substring(0, 10) : '');
                so.is_new_order = orderDate === todayStr;
                this.state.saleOrders.push(so);
            }
            if (typeof result.total_count === 'number') {
                this.state.totalCount = result.total_count;
            }
            // Cập nhật kanbanBatchSize để cache biết full dataset đã được tải
            this.state.kanbanBatchSize = this.state.saleOrders.length;
            await this._saveToCache({
                dashboard_stats: this.state.dashboardStats,
                orders: this.state.saleOrders,
                total_count: this.state.totalCount,
                warehouses: this.state.warehouses,
                tags: this.state.tags,
            });
            console.log('[DP AutoLoad] Loaded all', this.state.saleOrders.length, '/', this.state.totalCount, 'orders');
        } catch (e) {
            console.error('[DP AutoLoad] _autoLoadAllRemaining failed:', e);
        } finally {
            if (mySeq === this._autoLoadSeq) {
                this.state.isLoadingMore = false;
            }
        }
    }

    // --- Computed Filters & Pagination ---
}
