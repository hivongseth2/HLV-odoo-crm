/** @odoo-module **/

export class DeliveryPlannerKanbanSelectionMixin {
    async loadAllKanbanBatch() {
        if (this.state.isLoading || this.state.isLoadingMore || !this.hasMoreKanbanData) return;
        const remaining = this.remainingKanbanCount;
        if (!remaining) return;
        // Soft-confirm khi số đơn còn lại lớn để tránh tải nhầm gây lag
        if (remaining > 300) {
            const ok = window.confirm(`Tải tất cả ${remaining} đơn còn lại? Có thể chậm nếu số lượng lớn.`);
            if (!ok) return;
        }
        const currentLen = this.state.saleOrders.length;
        this.state.isLoadingMore = true;
        try {
            const result = await this.orm.call(
                "sale.order",
                "get_delivery_dashboard_data",
                [],
                {
                    ...this._buildFetchKwargs(),
                    limit: remaining,
                    offset: currentLen,
                    include_stats: false,
                }
            );
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
            this.state.kanbanBatchSize = this.state.saleOrders.length;
            await this._saveToCache({
                dashboard_stats: this.state.dashboardStats,
                orders: this.state.saleOrders,
                total_count: this.state.totalCount,
                warehouses: this.state.warehouses,
                tags: this.state.tags,
            });
        } catch (e) {
            console.error("loadAllKanbanBatch failed:", e);
        } finally {
            this.state.isLoadingMore = false;
        }
    }

    async loadMoreKanbanBatch() {
        if (this.state.isLoading || this.state.isLoadingMore || !this.hasMoreKanbanData) return;
        const BATCH = 100;
        const currentLen = this.state.saleOrders.length;
        this.state.isLoadingMore = true;
        try {
            const result = await this.orm.call(
                "sale.order",
                "get_delivery_dashboard_data",
                [],
                {
                    ...this._buildFetchKwargs(),
                    limit: BATCH,
                    offset: currentLen,
                    include_stats: false,
                }
            );
            const fresh = (result && result.orders) || [];
            const todayStr = new Date().toISOString().slice(0, 10);
            const existingIds = new Set(this.state.saleOrders.map(o => o.id));
            for (const so of fresh) {
                if (existingIds.has(so.id)) continue; // dedupe (e.g. bus update during fetch)
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
            this.state.kanbanBatchSize = this.state.saleOrders.length;
            // Persist appended state to cache
            await this._saveToCache({
                dashboard_stats: this.state.dashboardStats,
                orders: this.state.saleOrders,
                total_count: this.state.totalCount,
                warehouses: this.state.warehouses,
                tags: this.state.tags,
            });
        } catch (e) {
            console.error("loadMoreKanbanBatch failed:", e);
        } finally {
            this.state.isLoadingMore = false;
        }
    }

    // --- Returned / Stopped orders group ---
    get returnedOrders() {
        return this._applyArchiveFilter(this.state.saleOrders.filter(so => so.is_returned_or_stopped));
    }

    get returnedOrdersPaged() {
        return this.returnedOrders.slice(0, this.state.returnedColPageSize);
    }

    get hasMoreReturnedOrders() {
        return this.returnedOrders.length > this.state.returnedColPageSize;
    }

    loadMoreReturnedOrders() {
        this.state.returnedColPageSize += 15;
    }

    // --- Selection for Printing ---
    toggleSOSelection(soId) {
        if (this.state.selectedSOIds.has(soId)) {
            this.state.selectedSOIds.delete(soId);
        } else {
            this.state.selectedSOIds.add(soId);
        }
        // Force reactivity
        this.state.selectedSOIds = new Set(this.state.selectedSOIds);
    }

    isSOSelected(soId) {
        return this.state.selectedSOIds.has(soId);
    }

    selectAllInColumn(columnValue) {
        const ordersInColumn = this.ordersForColumn(columnValue);
        ordersInColumn.forEach(so => this.state.selectedSOIds.add(so.id));
        this.state.selectedSOIds = new Set(this.state.selectedSOIds);
    }

    deselectAllInColumn(columnValue) {
        const ordersInColumn = this.ordersForColumn(columnValue);
        ordersInColumn.forEach(so => this.state.selectedSOIds.delete(so.id));
        this.state.selectedSOIds = new Set(this.state.selectedSOIds);
    }

    clearAllSelections() {
        this.state.selectedSOIds.clear();
        this.state.selectedSOIds = new Set(this.state.selectedSOIds);
    }

    get allSelectedInColumn() {
        // Return object: { columnValue: boolean }
        const result = {};
        this.kanbanColumnDefs.forEach(col => {
            const ordersInCol = this.ordersForColumn(col.value);
            result[col.value] = ordersInCol.length > 0 &&
                ordersInCol.every(so => this.state.selectedSOIds.has(so.id));
        });
        return result;
    }

    get selectedCount() {
        return this.state.selectedSOIds.size;
    }

    getSelectedPickingIds() {
        const selectedIds = new Set(this.state.selectedSOIds);
        const pickingIds = [];
        const seenPickingIds = new Set();

        for (const so of this.state.saleOrders) {
            if (!selectedIds.has(so.id)) {
                continue;
            }
            for (const picking of so.pickings || []) {
                if (!picking || !picking.id) {
                    continue;
                }
                const sequenceCode = (picking.sequence_code || '').toUpperCase();
                if (!sequenceCode.includes('PICK')) {
                    continue;
                }
                if (picking.state === 'done' || picking.state === 'cancel' || picking.return_of_id) {
                    continue;
                }
                if (seenPickingIds.has(picking.id)) {
                    continue;
                }
                seenPickingIds.add(picking.id);
                pickingIds.push(picking.id);
            }
        }

        return pickingIds;
    }

    // toggle select print menu
    toggleSelectedPickingPrintMenu(ev) {
        ev.stopPropagation();
        if (this.state.selectedPrintMenuPos) {
            this.state.selectedPrintMenuPos = null;
            return;
        }
        const rect = ev.currentTarget.getBoundingClientRect();
        this.state.selectedPrintMenuPos = {
            top: rect.bottom + window.scrollY,
            right: window.innerWidth - rect.right,
        };

        // Chỉ show report có tên chứa "lấy hàng"
        this.state.selectedPrintMenuReports = this.state.pickingReports.filter((r) =>
            r.name.toLowerCase().includes('lấy hàng')
        );
    }

    closeSelectedPickingPrintMenu() {
        this.state.selectedPrintMenuPos = null;
    }
}
