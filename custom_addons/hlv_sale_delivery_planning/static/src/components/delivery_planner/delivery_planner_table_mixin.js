/** @odoo-module **/
// Purpose: Delivery planner mixin for table filters, sorting, resize, and row selection helpers.

export class DeliveryPlannerTableMixin {
    getSOPrintStatus(so) {
        const pickings = (so.pickings || []).filter(p => (p.sequence_code || '').toUpperCase().startsWith('PICK'));
        if (!pickings.length) return 'none';
        const printed = pickings.filter(p => p.printed).length;
        if (printed === 0) return 'unprinted';
        if (printed === pickings.length) return 'printed';
        return 'partial';
    }

    getPrintStatusLabel(status) {
        return ({
            none: '—',
            unprinted: 'Chưa in',
            partial: 'In một phần',
            printed: 'Đã in',
        })[status] || '—';
    }

    getPrintStatusBadgeClass(status) {
        return ({
            none: 'bg-light text-muted',
            unprinted: 'bg-danger text-white',
            partial: 'bg-warning text-dark',
            printed: 'bg-success text-white',
        })[status] || 'bg-light text-muted';
    }

    /**
     * Compute shipper-receive status of a SO based on its outbound pickings:
     *   - 'none'      : không có phiếu PICK
     *   - 'unreceived': chưa shipper nào nhận
     *   - 'partial'   : nhận một phần
     *   - 'received'  : tất cả đã nhận
     */
    getSOReceiveStatus(so) {
        const pickings = (so.pickings || []).filter(p => (p.sequence_code || '').toUpperCase().startsWith('PICK'));
        if (!pickings.length) return 'none';
        const received = pickings.filter(p => p.shipper_received).length;
        if (received === 0) return 'unreceived';
        if (received === pickings.length) return 'received';
        return 'partial';
    }

    getReceiveStatusLabel(status) {
        return ({
            none: '—',
            unreceived: 'Chưa nhận',
            partial: 'Nhận một phần',
            received: 'Đã nhận',
        })[status] || '—';
    }

    getReceiveStatusBadgeClass(status) {
        return ({
            none: 'bg-light text-muted',
            unreceived: 'bg-secondary text-white',
            partial: 'bg-warning text-dark',
            received: 'bg-info text-dark',
        })[status] || 'bg-light text-muted';
    }

    /** Sorted client-side based on tableSortField/tableSortDir.
     *  Filtering is now done on the BACKEND via state.filter* fields. */
    get tableSortedOrders() {
        const orders = this._applyArchiveFilter(this.state.saleOrders || []);
        const field = this.state.tableSortField;
        const dir = this.state.tableSortDir === 'asc' ? 1 : -1;
        const getVal = (so) => {
            switch (field) {
                case 'name': return so.name || '';
                case 'misa_order_date': return so.misa_order_date || '';
                case 'partner': return (so.partner_id && so.partner_id[1]) || '';
                case 'warehouse': return (so.warehouse_id && so.warehouse_id[1]) || '';
                case 'delivery_status': return so.real_delivery_status || so.delivery_status || '';
                case 'stock_status': return so.stock_status || '';
                case 'packing_status': return so.packing_status || '';
                case 'commitment_date': return so.commitment_date || '';
                case 'amount_total': return Number(so.amount_total) || 0;
                default: return '';
            }
        };
        // Copy first to avoid mutating the reactive proxy in-place
        const arr = orders.slice();
        arr.sort((a, b) => {
            const va = getVal(a);
            const vb = getVal(b);
            if (typeof va === 'number' && typeof vb === 'number') {
                return (va - vb) * dir;
            }
            return String(va).localeCompare(String(vb), 'vi') * dir;
        });
        // Khi toàn bộ đơn đã được tải vào memory (sau auto-load),
        // phân trang client-side để tránh gọi server thêm.
        const allLoaded = this.state.totalCount > 0 && arr.length >= this.state.totalCount;
        if (allLoaded) {
            const start = (this.state.currentPage - 1) * this.state.itemsPerPage;
            return arr.slice(start, start + this.state.itemsPerPage);
        }
        return arr;
    }

    /** Color-code main row by status (delivery + packing) */
    getTableRowClass(so) {
        const classes = ['cursor-pointer'];
        const ds = so.real_delivery_status || so.delivery_status;
        if (ds === 'full') {
            classes.push('hlv-row-delivered');
        } else if (so.stock_status === 'out_of_stock') {
            classes.push('hlv-row-oos');
        } else if (so.stock_status === 'partial_ready') {
            classes.push('hlv-row-partial');
        } else if (so.stock_status === 'ready') {
            classes.push('hlv-row-ready');
        }
        if (so.is_returned_or_stopped) {
            classes.push('hlv-row-stopped');
        }
        if (so.has_unread_message) {
            classes.push('hlv-row-unread');
        }
        return classes.join(' ');
    }

    /** Collect distinct shipper names from active pickings */
    getShippersForSO(so) {
        const seen = new Set();
        const out = [];
        for (const pk of (so.pickings || [])) {
            const u = pk.shipper_user;
            if (u && !seen.has(u)) {
                seen.add(u);
                out.push(u);
            }
        }
        return out;
    }

    /** Select / deselect all SO currently visible (sorted page) */
    toggleSelectAllVisibleSO() {
        const visible = this.tableSortedOrders;
        const allSelected = visible.length > 0 &&
            visible.every(so => this.state.selectedSOIds.has(so.id));
        if (allSelected) {
            visible.forEach(so => this.state.selectedSOIds.delete(so.id));
        } else {
            visible.forEach(so => this.state.selectedSOIds.add(so.id));
        }
        this.state.selectedSOIds = new Set(this.state.selectedSOIds);
    }

    get allTableRowsSelected() {
        const visible = this.tableSortedOrders;
        return visible.length > 0 &&
            visible.every(so => this.state.selectedSOIds.has(so.id));
    }

    /** Column resize: drag right border of <th> to change its width */
    onColResizeStart(ev, colKey) {
        ev.stopPropagation();
        ev.preventDefault();
        const th = ev.target.closest('th');
        if (!th) return;
        const startX = ev.clientX;
        const startWidth = th.offsetWidth;
        const onMove = (e) => {
            const delta = e.clientX - startX;
            const newW = Math.max(80, startWidth + delta);
            th.style.width = newW + 'px';
            th.style.minWidth = newW + 'px';
        };
        const onUp = () => {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            document.body.style.userSelect = '';
        };
        document.body.style.userSelect = 'none';
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    }

    setKanbanGroupBy(dim) {
        this.state.kanbanGroupBy = dim;
        this.state.kanbanColumnOrder = {};
        this.state.kanbanColPageSize = {};
    }

    // --- Kanban Column Definitions ---
    get kanbanColumnDefs() {
        switch (this.state.kanbanGroupBy) {
            case 'delivery_status': return [
                { value: 'pending', label: 'Chưa Giao', badgeClass: 'bg-danger', textClass: 'text-danger', iconClass: 'fa fa-clock-o', progressClass: 'bg-danger' },
                { value: 'partial', label: 'Giao 1 Phần', badgeClass: 'bg-warning text-dark', textClass: 'text-warning', iconClass: 'fa fa-truck', progressClass: 'bg-warning' },
                { value: 'full', label: 'Đã Giao Đủ', badgeClass: 'bg-success', textClass: 'text-success', iconClass: 'fa fa-check-circle', progressClass: 'bg-success' },
            ];
            case 'stock_status': return [
                { value: 'out_of_stock', label: 'Không Có Hàng', badgeClass: 'bg-danger', textClass: 'text-danger', iconClass: 'fa fa-times-circle', progressClass: 'bg-danger' },
                { value: 'partial_ready', label: 'Có Hàng 1 Phần', badgeClass: 'bg-warning text-dark', textClass: 'text-warning', iconClass: 'fa fa-exclamation-circle', progressClass: 'bg-warning' },
                { value: 'ready', label: 'Đủ Hàng Xuất', badgeClass: 'bg-success', textClass: 'text-success', iconClass: 'fa fa-check', progressClass: 'bg-success' },
            ];
            case 'packing_status': return [
                { value: 'waiting_stock', label: 'Không Có Hàng Đóng', badgeClass: 'bg-secondary', textClass: 'text-secondary', iconClass: 'fa fa-hourglass-start', progressClass: 'bg-secondary' },
                { value: 'unpacked', label: 'Có Hàng Chưa Đóng Gói', badgeClass: 'bg-warning text-dark', textClass: 'text-warning', iconClass: 'fa fa-exclamation-triangle', progressClass: 'bg-warning' },
                { value: 'printed_waiting', label: 'Đã In, Chờ Đóng Gói', badgeClass: 'bg-info', textClass: 'text-info', iconClass: 'fa fa-print', progressClass: 'bg-info' },
                { value: 'packed_waiting_ship', label: 'Đã Gói, Chờ Nhận Giao', badgeClass: 'bg-primary', textClass: 'text-primary', iconClass: 'fa fa-archive', progressClass: 'bg-primary' },
                { value: 'shipping', label: 'Đang Giao', badgeClass: 'bg-success', textClass: 'text-success', iconClass: 'fa fa-motorcycle', progressClass: 'bg-success' },
                { value: 'delivered_today', label: 'Đã Giao Trong Ngày', badgeClass: 'bg-success bg-opacity-75', textClass: 'text-success', iconClass: 'fa fa-calendar-check-o', progressClass: 'bg-success' },
            ];
            default: return [];
        }
    }

    // Internal: toàn bộ SO của cột (theo DnD order)
    _allOrdersForColumn(colValue) {
        const dim = this.state.kanbanGroupBy;
        const fieldMap = {
            delivery_status: 'real_delivery_status',
            stock_status: 'stock_status',
            packing_status: 'packing_status',
        };
        const field = fieldMap[dim];

        const base = this._applyArchiveFilter(this.state.saleOrders || []).filter(so => {
            if (so.is_returned_or_stopped) return false;   // hiện riêng trong cột "Trả hàng"
            let val = so[field];
            if (dim === 'delivery_status' && val === 'unshipped') val = 'pending';
            if (dim === 'packing_status') {
                // delivered_today: ưu tiên CAO NHẤT
                // - Đã giao hôm nay (kể cả partial) VÀ không có PICK nào assigned sẵn hàng
                if (so.has_delivered_today && (so.real_delivery_status === 'full' || !so.has_assigned_pick)) {
                    val = 'delivered_today';
                } else if (so.real_delivery_status === 'full') {
                    return false;
                }
                // Shipper đã nhận → "Đang giao"
                else if (so.has_shipper_received) val = 'shipping';
                // Đã đóng gói đủ → chuyển sang cột "Đã gói, chờ nhận giao"
                else if (val === 'fully_packed') val = 'packed_waiting_ship';
                // Active PICK đã in → "Đã in, chờ đóng gói"
                else if (so.has_active_pick_printed) val = 'printed_waiting';
                // Gơm nhóm: còn hàng chưa đóng = cần xử lý ngay.
                else if (val === 'partial_packed') val = 'unpacked';
            }
            return val === colValue;
        });

        const order = this.state.kanbanColumnOrder[colValue];
        if (!order || !order.length) return base;
        const orderMap = {};
        order.forEach((id, idx) => { orderMap[id] = idx; });
        return [...base].sort((a, b) => (orderMap[a.id] ?? 9999) - (orderMap[b.id] ?? 9999));
    }

    // Public: chỉ trả N card đầu (phân trang client-side)
    ordersForColumn(colValue) {
        const pageSize = this.state.kanbanColPageSize[colValue] || 15;
        return this._allOrdersForColumn(colValue).slice(0, pageSize);
    }

    totalInColumn(colValue) {
        return this._allOrdersForColumn(colValue).length;
    }

    hasMoreInColumn(colValue) {
        const pageSize = this.state.kanbanColPageSize[colValue] || 15;
        return this._allOrdersForColumn(colValue).length > pageSize;
    }

    loadMoreColumn(colValue) {
        const current = this.state.kanbanColPageSize[colValue] || 15;
        this.state.kanbanColPageSize[colValue] = current + 15;
    }

    get hasMoreKanbanData() {
        return this.state.viewMode === 'kanban' && this.state.saleOrders.length < this.state.totalCount;
    }

    get remainingKanbanCount() {
        return Math.max(0, (this.state.totalCount || 0) - (this.state.saleOrders || []).length);
    }

    /**
     * Tải hết các đơn còn lại trong Kanban với MỘT request duy nhất
     * (limit = số còn lại). Có confirm để tránh bấm nhầm.
     */
}
