/** @odoo-module **/

export class DeliveryPlannerPreferencesMixin {
    get totalPages() {
        return Math.ceil(this.state.totalCount / this.state.itemsPerPage) || 1;
    }

    get paginatedOrders() {
        return this._applyArchiveFilter(this.state.saleOrders);
    }

    /**
     * Apply the archive / consolidate view filter:
     *  - archivedView = 'archived'    → only archived SOs
     *  - archivedView = 'consolidate' → only consolidate (chờ gom) SOs
     *  - archivedView = 'none'        → all SOs except archived AND consolidate
     */
    _applyArchiveFilter(orders) {
        const archived = this.state.archivedSOIds;
        const consolidate = this.state.consolidateSOIds;
        if (this.state.archivedView === 'archived') {
            return orders.filter(so => archived.has(so.id));
        }
        if (this.state.archivedView === 'consolidate') {
            return orders.filter(so => consolidate.has(so.id));
        }
        if (!archived.size && !consolidate.size) return orders;
        return orders.filter(so => !archived.has(so.id) && !consolidate.has(so.id));
    }

    isSOArchived(soId) {
        return this.state.archivedSOIds.has(soId);
    }

    isSOConsolidate(soId) {
        return this.state.consolidateSOIds.has(soId);
    }

    async toggleArchiveSO(soId) {
        if (!soId) return;
        const wasArchived = this.state.archivedSOIds.has(soId);
        // Optimistic UI: archive và consolidate là mutually exclusive.
        if (wasArchived) {
            this.state.archivedSOIds.delete(soId);
        } else {
            this.state.archivedSOIds.add(soId);
            this.state.consolidateSOIds.delete(soId);
        }
        try {
            const res = await this.orm.call(
                'hlv.delivery.planner.user.pref', 'toggle_archive', [], { so_id: soId }
            );
            this.state.archivedSOIds = new Set(res.archived_so_ids || []);
            this.state.consolidateSOIds = new Set(res.consolidate_so_ids || []);
        } catch (e) {
            console.error('toggle_archive failed:', e);
            if (wasArchived) {
                this.state.archivedSOIds.add(soId);
            } else {
                this.state.archivedSOIds.delete(soId);
            }
            this.notification.add('Không thể cập nhật trạng thái cất đơn', {
                type: 'danger', title: 'Lỗi',
            });
        }
    }

    async toggleConsolidateSO(soId) {
        if (!soId) return;
        const wasInBucket = this.state.consolidateSOIds.has(soId);
        if (wasInBucket) {
            this.state.consolidateSOIds.delete(soId);
        } else {
            this.state.consolidateSOIds.add(soId);
            this.state.archivedSOIds.delete(soId);
        }
        try {
            const res = await this.orm.call(
                'hlv.delivery.planner.user.pref', 'toggle_consolidate', [], { so_id: soId }
            );
            this.state.archivedSOIds = new Set(res.archived_so_ids || []);
            this.state.consolidateSOIds = new Set(res.consolidate_so_ids || []);
        } catch (e) {
            console.error('toggle_consolidate failed:', e);
            if (wasInBucket) {
                this.state.consolidateSOIds.add(soId);
            } else {
                this.state.consolidateSOIds.delete(soId);
            }
            this.notification.add('Không thể cập nhật đơn chờ gom', {
                type: 'danger', title: 'Lỗi',
            });
        }
    }

    toggleShowArchivedOnly() {
        // Cycle through views: 'none' → 'archived' → 'consolidate' → 'none'
        const nextView = {
            'none': 'archived',
            'archived': 'consolidate',
            'consolidate': 'none'
        }[this.state.archivedView] || 'none';
        this.setArchivedView(nextView);
    }

    setArchivedView(mode) {
        // mode: 'none' | 'archived' | 'consolidate'
        this.state.archivedView = (['archived', 'consolidate'].includes(mode)) ? mode : 'none';
        this.state.showArchivedOnly = (this.state.archivedView === 'archived');
    }

    async clearAllArchived() {
        if (!this.state.archivedSOIds.size) return;
        if (!window.confirm('Phục hồi tất cả ' + this.state.archivedSOIds.size + ' đơn đã cất?')) return;
        try {
            const res = await this.orm.call(
                'hlv.delivery.planner.user.pref', 'set_archived', [], { so_ids: [] }
            );
            this.state.archivedSOIds = new Set(res.archived_so_ids || []);
            this.state.consolidateSOIds = new Set(res.consolidate_so_ids || []);
            if (this.state.archivedView === 'archived') this.setArchivedView('none');
        } catch (e) {
            console.error('clearAllArchived failed:', e);
            this.notification.add('Không thể phục hồi đơn đã cất', {
                type: 'danger', title: 'Lỗi',
            });
        }
    }

    async clearAllConsolidate() {
        if (!this.state.consolidateSOIds.size) return;
        if (!window.confirm('Bỏ gom tất cả ' + this.state.consolidateSOIds.size + ' đơn chờ gom?')) return;
        try {
            const res = await this.orm.call(
                'hlv.delivery.planner.user.pref', 'set_consolidate', [], { so_ids: [] }
            );
            this.state.archivedSOIds = new Set(res.archived_so_ids || []);
            this.state.consolidateSOIds = new Set(res.consolidate_so_ids || []);
            if (this.state.archivedView === 'consolidate') this.setArchivedView('none');
        } catch (e) {
            console.error('clearAllConsolidate failed:', e);
            this.notification.add('Không thể bỏ gom đơn', {
                type: 'danger', title: 'Lỗi',
            });
        }
    }

    /**
     * Load per-user preferences from backend on startup. Applies the saved
     * default filter set IN PLACE on this.state, so the first fetchData()
     * call uses them. Falls back silently if the model is missing (module
     * not yet upgraded) — UI still works, just without backend persistence.
     */
    async _loadUserPreferences() {
        try {
            const res = await this.orm.call(
                'hlv.delivery.planner.user.pref', 'get_user_preferences', [], {}
            );
            this.state.archivedSOIds = new Set(res.archived_so_ids || []);
            this.state.consolidateSOIds = new Set(res.consolidate_so_ids || []);
            const defaults = res.default_filters || {};
            if (defaults && Object.keys(defaults).length) {
                this._applyFilterSnapshot(defaults);
                this.state.hasDefaultFilters = true;
            }
        } catch (e) {
            console.warn('[DP Pref] could not load user preferences:', e);
        }
    }

    /**
     * Snapshot of all filter form state — keys MUST match _applyFilterSnapshot
     * (and _buildFetchKwargs where applicable). Stored as JSON in user pref.
     */
    _buildFilterSnapshot() {
        const s = this.state;
        return {
            searchQuery: s.searchQuery,
            filterWarehouseId: s.filterWarehouseId,
            filterDeliveryStatus: s.filterDeliveryStatus,
            filterStockStatus: s.filterStockStatus,
            filterPackingStatus: s.filterPackingStatus,
            filterDateFrom: s.filterDateFrom,
            filterDateTo: s.filterDateTo,
            filterDoneDateFrom: s.filterDoneDateFrom,
            filterDoneDateTo: s.filterDoneDateTo,
            filterPODateFrom: s.filterPODateFrom,
            filterPODateTo: s.filterPODateTo,
            filterPOStatus: s.filterPOStatus,
            filterSalerCode: s.filterSalerCode,
            filterHtgh: s.filterHtgh,
            filterDeliveryType: s.filterDeliveryType,
            filterTagIds: Array.from(s.filterTagIds || []),
            showCompleted: s.showCompleted,
            filterNeedTransfer: s.filterNeedTransfer,
            filterNewOrders: s.filterNewOrders,
            viewMode: s.viewMode,
            kanbanGroupBy: s.kanbanGroupBy,
        };
    }

    _applyFilterSnapshot(snap) {
        if (!snap || typeof snap !== 'object') return;
        const s = this.state;
        const assign = (key, fallback) => {
            if (snap[key] !== undefined && snap[key] !== null) s[key] = snap[key];
            else if (fallback !== undefined) s[key] = fallback;
        };
        assign('searchQuery');
        assign('filterWarehouseId');
        assign('filterDeliveryStatus');
        assign('filterStockStatus');
        assign('filterPackingStatus');
        assign('filterDateFrom');
        assign('filterDateTo');
        assign('filterDoneDateFrom');
        assign('filterDoneDateTo');
        assign('filterPODateFrom');
        assign('filterPODateTo');
        assign('filterPOStatus');
        assign('filterSalerCode');
        assign('filterHtgh');
        assign('filterDeliveryType');
        if (Array.isArray(snap.filterTagIds)) s.filterTagIds = snap.filterTagIds.slice();
        assign('showCompleted');
        assign('filterNeedTransfer');
        assign('filterNewOrders');
        assign('viewMode');
        assign('kanbanGroupBy');
    }

    /** Save the current filter form as the user's default. */
    async saveCurrentFiltersAsDefault() {
        try {
            const snap = this._buildFilterSnapshot();
            await this.orm.call(
                'hlv.delivery.planner.user.pref', 'save_default_filters',
                [], { filters: snap }
            );
            this.state.hasDefaultFilters = true;
            this.notification.add('Đã lưu bộ lọc mặc định cho bạn', {
                type: 'success', title: 'Lưu thành công',
            });
        } catch (e) {
            console.error('saveCurrentFiltersAsDefault failed:', e);
            this.notification.add('Không thể lưu bộ lọc mặc định', {
                type: 'danger', title: 'Lỗi',
            });
        }
    }

    async clearDefaultFilters() {
        if (!window.confirm('Xoá bộ lọc mặc định đã lưu?')) return;
        try {
            await this.orm.call(
                'hlv.delivery.planner.user.pref', 'clear_default_filters', [], {}
            );
            this.state.hasDefaultFilters = false;
            this.notification.add('Đã xoá bộ lọc mặc định', { type: 'info' });
        } catch (e) {
            console.error('clearDefaultFilters failed:', e);
        }
    }

    // --- Actions ---
    async nextPage() {
        if (this.state.currentPage < this.totalPages) {
            this.state.currentPage++;
            // Khi đã tải hết đơn vào memory, phân trang client-side (không cần gọi server)
            if (this.state.saleOrders.length < this.state.totalCount) {
                await this.fetchData();
            }
        }
    }

    async prevPage() {
        if (this.state.currentPage > 1) {
            this.state.currentPage--;
            // Khi đã tải hết đơn vào memory, phân trang client-side (không cần gọi server)
            if (this.state.saleOrders.length < this.state.totalCount) {
                await this.fetchData();
            }
        }
    }

    /**
     * Cho phép user tự chọn số dòng/trang ở bảng (Card/Table view).
     * Lưu localStorage để nhớ pref qua các phiên.
     */
    async onItemsPerPageChange(ev) {
        var n = parseInt(ev.target.value, 10);
        if (![12, 25, 50, 100, 200].includes(n)) n = 12;
        this.state.itemsPerPage = n;
        this.state.currentPage = 1;
        try { localStorage.setItem('hlv_dp_items_per_page', String(n)); } catch (e) { /* quota / private mode */ }
        await this.fetchData();
    }

    async onFilterChange() {
        this.state.currentPage = 1;
        this.state.kanbanColumnOrder = {};
        this.state.kanbanColPageSize = {};
        this.state.kanbanBatchSize = 100;
        this.state.returnedColPageSize = 15;
        // Xóa selection khi filter thay đổi (tránh giữ đơn không còn trong view)
        this.state.selectedSOIds = new Set();
        await this.fetchData();
    }

    // --- View Mode Toggle ---
    async setViewMode(mode) {
        this.state.viewMode = mode;
        if (mode === 'kanban') {
            // Mặc định: chỉ hiện đơn chưa giao + giao 1 phần (tiết kiệm tải)
            if (this.state.filterDeliveryStatus === 'all') {
                this.state.filterDeliveryStatus = 'pending_partial';
            }
            this.state.filterStockStatus = 'all';
            this.state.kanbanColumnOrder = {};
            this.state.kanbanColPageSize = {};
            this.state.kanbanBatchSize = 100;
        }
        this.state.currentPage = 1;
        await this.fetchData();
    }

    // ============================================================
    // TABLE (BẢNG) VIEW HELPERS
    // ============================================================
    toggleTableSort(field) {
        if (this.state.tableSortField === field) {
            this.state.tableSortDir = this.state.tableSortDir === 'asc' ? 'desc' : 'asc';
        } else {
            this.state.tableSortField = field;
            this.state.tableSortDir = 'asc';
        }
    }

    /**
     * Reset toàn bộ filter cột Bảng (các filter backend được bind từ
     * dropdown trên column header) về giá trị mặc định và refetch backend.
     */
    async resetTableColumnFilters() {
        this.state.filterWarehouseId = 'all';
        this.state.filterDeliveryStatus = 'all';
        this.state.filterStockStatus = 'all';
        this.state.filterPackingStatus = 'all';
        this.state.filterDeliveryType = 'all';
        this.state.filterTagIds = [];
        this.state.filterPrintStatus = 'all';
        this.state.filterShipperReceived = 'all';
        this.state.filterHtgh = '';
        this.state.filterSalerCode = '';
        this.state.searchQuery = '';
        this.state.filterDateFrom = '';
        await this.onFilterChange();
    }

    toggleTableRowExpand(soId) {
        if (this.state.expandedTableRows.has(soId)) {
            this.state.expandedTableRows.delete(soId);
        } else {
            this.state.expandedTableRows.add(soId);
        }
        // Force reactivity
        this.state.expandedTableRows = new Set(this.state.expandedTableRows);
    }

    isTableRowExpanded(soId) {
        return this.state.expandedTableRows.has(soId);
    }

    /**
     * Debounced backend filter trigger for Bảng column text inputs.
     * Updates `state[stateKey]` immediately (so input value is responsive)
     * but waits 400ms of idle before calling onFilterChange() → backend.
     */
    setTableFilterDebounced(stateKey, value) {
        this.state[stateKey] = value;
        if (this._tableFilterDebounceTimer) {
            clearTimeout(this._tableFilterDebounceTimer);
        }
        this._tableFilterDebounceTimer = setTimeout(() => {
            this._tableFilterDebounceTimer = null;
            this.onFilterChange();
        }, 400);
    }

    /** True if any filter beyond the defaults is active (used to show "clear" button on Bảng) */
    get hasAnyTableFilter() {
        const s = this.state;
        return (
            (s.searchQuery && s.searchQuery.trim()) ||
            (s.filterWarehouseId && s.filterWarehouseId !== 'all') ||
            (s.filterDeliveryStatus && s.filterDeliveryStatus !== 'all' && s.filterDeliveryStatus !== 'pending_partial') ||
            (s.filterStockStatus && s.filterStockStatus !== 'all') ||
            (s.filterPackingStatus && s.filterPackingStatus !== 'all') ||
            (s.filterDeliveryType && s.filterDeliveryType !== 'all') ||
            (s.filterHtgh && s.filterHtgh.trim()) ||
            (s.filterSalerCode && s.filterSalerCode.trim()) ||
            (s.filterTagIds && s.filterTagIds.length > 0)
        );
    }

    /** Reset all Bảng-relevant filters to default and refetch */
    async clearAllTableFilters() {
        this.state.searchQuery = '';
        this.state.filterWarehouseId = 'all';
        this.state.filterDeliveryStatus = 'pending_partial';
        this.state.filterStockStatus = 'all';
        this.state.filterPackingStatus = 'all';
        this.state.filterDeliveryType = 'all';
        this.state.filterHtgh = '';
        this.state.filterSalerCode = '';
        this.state.filterTagIds = [];
        await this.onFilterChange();
    }

    /**
     * Compute the print status of a SO based on its outbound (PICK) pickings:
     *   - 'none'    : không có phiếu PICK
     *   - 'unprinted'  : có phiếu nhưng chưa in cái nào
     *   - 'partial'    : in một phần
     *   - 'printed'    : tất cả PICK đã in
     */
}
