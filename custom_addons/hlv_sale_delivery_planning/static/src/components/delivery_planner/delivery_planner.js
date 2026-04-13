/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import {
    translateDeliveryStatus, translatePickingState, translatePickingStatus,
    translateStockStatus, translatePackingStatus, translateSOStatus, translatePOStatus,
    getPickingStateBadgeClass, getPickingStatusBadgeClass, getDeliveryStatusBadgeClass,
    getStockStatusBadgeClass, getPackingStatusBadgeClass, getPOStatusBadgeClass,
    getSOCardColorClass, formatCurrency, formatQty, getDatesComparisonClass,
} from "./delivery_planner_utils";

export class DeliveryPlannerDashboard extends Component {
    static template = "hlv_sale_delivery_planning.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({
            saleOrders: [],
            warehouses: [],
            tags: [],
            isLoading: true,

            // Search & Filters
            searchQuery: "",
            filterWarehouseId: "all",
            filterDeliveryStatus: "pending_partial",
            filterStockStatus: "all",
            filterDateFrom: "",
            filterDateTo: null,
            filterPODateFrom: null,
            filterPODateTo: null,
            filterPOStatus: "all",
            filterPackingStatus: "all",
            filterSalerCode: "",
            filterHtgh: "",
            filterDeliveryType: "all",
            filterTagIds: [],
            filterNeedTransfer: false,
            showCompleted: false,

            // HTGH presets (lưu localStorage)
            htghPresets: JSON.parse(localStorage.getItem('hlv_htgh_presets') || 'null') || [
                { label: 'Hãng VC', value: 'ghn,cpn,chuy\u1ec3n ph\u00e1t nhanh,giao h\u00e0ng nhanh,j&t' },
                { label: 'Tr\u1eeb h\u00e3ng VC', value: '!ghn,!cpn,!chuy\u1ec3n ph\u00e1t nhanh,!giao h\u00e0ng nhanh,!j&t' },
            ],

            // Stats
            dashboardStats: { total: 0, ready: 0, partial: 0, out_of_stock: 0 },

            // Pagination
            currentPage: 1,
            itemsPerPage: 12,
            totalCount: 0,

            // Drawer
            isDrawerOpen: false,
            selectedOrder: null,

            // Package Modal
            isPackageModalOpen: false,
            selectedPackage: null,

            // UI State
            collapsedSections: new Set(['packages', 'flows', 'pending_products']), // Default collapsed

            // View Mode
            viewMode: 'kanban',               // 'list' | 'kanban'
            kanbanGroupBy: 'packing_status', // 'packing_status' | 'delivery_status' | 'stock_status'
            draggedSoId: null,
            dragOverColumn: null,
            kanbanColumnOrder: {},           // { colValue: [soId, ...] } — thứ tự DnD client-side
            kanbanColPageSize: {},           // { colValue: N } — số card hiển thị mỗi cột
            kanbanBatchSize: 200,            // số đơn tải backend cho toàn kanban

            // Selection for printing
            selectedSOIds: new Set(),        // Set of selected sale order IDs for printing

            // Returned/Stopped group paging
            returnedColPageSize: 15,

            // Transfer Modal
            isTransferModalOpen: false,
            transferModalLoading: false,
            transferModalData: null,         // { warehouses, all_partners }
            transferSelections: {},          // { [wh_id]: { selected, partner_id, products: {[prod_id]: {include, qty}} } }
            isCreatingTransfer: false,

            // Relocation Modal (Chuyển vị trí)
            isRelocationModalOpen: false,
            relocationModalLoading: false,
            relocationModalData: null,       // { orders, dest_locations, default_dest_location_id }
            relocationDestLocationId: null,
            relocationSaveDefault: false,
            relocationOrderSelections: {},   // { [so_id]: { selected, products: {[prod_id]: { include, qty }} } }
            isCreatingRelocation: false,

            // Picking print menu
            pickingReports: [],       // [{id, name, report_type}] — báo cáo có thể in cho stock.picking
            printMenuPickingId: null, // picking.id đang hiển thị menu in
        });

        onWillStart(async () => {
            const [, reports] = await Promise.all([
                this.fetchData(),
                this.orm.searchRead(
                    'ir.actions.report',
                    [['model', '=', 'stock.picking'], ['binding_model_id', '!=', false]],
                    ['id', 'name', 'report_type'],
                    { order: 'name' }
                )
            ]);
            this.state.pickingReports = reports;
        });
    }

    async fetchData() {
        this.state.isLoading = true;
        const isKanban = this.state.viewMode === 'kanban';
        try {
            const result = await this.orm.call(
                "sale.order",
                "get_delivery_dashboard_data",
                [],
                {
                    search_query: this.state.searchQuery.trim(),
                    filter_warehouse_id: this.state.filterWarehouseId,
                    filter_delivery_status: this.state.filterDeliveryStatus,
                    filter_stock_status: this.state.filterStockStatus,
                    filter_date_from: this.state.filterDateFrom,
                    filter_date_to: this.state.filterDateTo,
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
                    // Kanban tải theo batch, không phân trang backend
                    limit: isKanban ? this.state.kanbanBatchSize : this.state.itemsPerPage,
                    offset: isKanban ? 0 : (this.state.currentPage - 1) * this.state.itemsPerPage,
                }
            );

            this.state.dashboardStats = result.dashboard_stats || { total: 0, ready: 0, partial: 0, out_of_stock: 0 };
            const fetchedOrders = result.orders || [];
            this.state.saleOrders = fetchedOrders.map(so => {
                so.flows = so.flows || [];
                so.pickings = so.pickings || [];
                so.lines = so.lines || [];
                so.pos = so.pos || [];

                // Map of name -> node for finding parent
                const nodeByName = {};
                so.flows.forEach(flow => {
                    (flow.nodes || []).forEach(node => {
                        nodeByName[node.name] = node;
                    });
                });

                // Assign persistent visual link info
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

                return so;
            });
            this.state.totalCount = result.total_count || 0;
            if (this.state.warehouses.length === 0) {
                this.state.warehouses = result.warehouses || [];
            }
            if (this.state.tags.length === 0) {
                this.state.tags = result.tags || [];
            }
        } catch (error) {
            console.error("Lỗi khi tải dữ liệu bảng điều phối:", error);
        } finally {
            this.state.isLoading = false;
        }
    }

    // --- Computed Filters & Pagination ---
    get totalPages() {
        return Math.ceil(this.state.totalCount / this.state.itemsPerPage) || 1;
    }

    get paginatedOrders() {
        return this.state.saleOrders;
    }

    // --- Actions ---
    async nextPage() {
        if (this.state.currentPage < this.totalPages) {
            this.state.currentPage++;
            await this.fetchData();
        }
    }

    async prevPage() {
        if (this.state.currentPage > 1) {
            this.state.currentPage--;
            await this.fetchData();
        }
    }

    async onFilterChange() {
        this.state.currentPage = 1;
        this.state.kanbanColumnOrder = {};
        this.state.kanbanColPageSize = {};
        this.state.kanbanBatchSize = 200;
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
            this.state.kanbanBatchSize = 200;
        }
        this.state.currentPage = 1;
        await this.fetchData();
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
                { value: 'pending',  label: 'Chưa Giao',    badgeClass: 'bg-danger',             textClass: 'text-danger',   iconClass: 'fa fa-clock-o',        progressClass: 'bg-danger' },
                { value: 'partial',  label: 'Giao 1 Phần',  badgeClass: 'bg-warning text-dark',  textClass: 'text-warning',  iconClass: 'fa fa-truck',          progressClass: 'bg-warning' },
                { value: 'full',     label: 'Đã Giao Đủ',   badgeClass: 'bg-success',            textClass: 'text-success',  iconClass: 'fa fa-check-circle',   progressClass: 'bg-success' },
            ];
            case 'stock_status': return [
                { value: 'out_of_stock',   label: 'Không Có Hàng',   badgeClass: 'bg-danger',            textClass: 'text-danger',   iconClass: 'fa fa-times-circle',   progressClass: 'bg-danger' },
                { value: 'partial_ready',  label: 'Có Hàng 1 Phần',  badgeClass: 'bg-warning text-dark', textClass: 'text-warning',  iconClass: 'fa fa-exclamation-circle', progressClass: 'bg-warning' },
                { value: 'ready',          label: 'Đủ Hàng Xuất',    badgeClass: 'bg-success',           textClass: 'text-success',  iconClass: 'fa fa-check',          progressClass: 'bg-success' },
            ];
            case 'packing_status': return [
                { value: 'waiting_stock',    label: 'Không Có Hàng Đóng',      badgeClass: 'bg-secondary',          textClass: 'text-secondary', iconClass: 'fa fa-hourglass-start', progressClass: 'bg-secondary' },
                { value: 'unpacked',         label: 'Có Hàng Chưa Đóng Gói',   badgeClass: 'bg-warning text-dark',  textClass: 'text-warning',   iconClass: 'fa fa-exclamation-triangle', progressClass: 'bg-warning' },
                { value: 'has_unprinted',    label: 'Có Phiếu Chưa In',        badgeClass: 'bg-danger',             textClass: 'text-danger',    iconClass: 'fa fa-exclamation-circle', progressClass: 'bg-danger' },
                { value: 'printed_waiting',  label: 'Đã In, Chờ Đóng Gói',     badgeClass: 'bg-info',               textClass: 'text-info',      iconClass: 'fa fa-print', progressClass: 'bg-info' },
                { value: 'packed_waiting_ship', label: 'Đã Gói, Chờ Nhận Giao', badgeClass: 'bg-primary',           textClass: 'text-primary',   iconClass: 'fa fa-archive', progressClass: 'bg-primary' },
                { value: 'shipping',         label: 'Đang Giao',               badgeClass: 'bg-success',            textClass: 'text-success',   iconClass: 'fa fa-motorcycle', progressClass: 'bg-success' },
            ];
            default: return [];
        }
    }

    // Internal: toàn bộ SO của cột (theo DnD order)
    _allOrdersForColumn(colValue) {
        const dim = this.state.kanbanGroupBy;
        const fieldMap = {
            delivery_status: 'real_delivery_status',
            stock_status:    'stock_status',
            packing_status:  'packing_status',
        };
        const field = fieldMap[dim];

        const needTransfer = this.state.filterNeedTransfer;
        const base = this.state.saleOrders.filter(so => {
            if (so.is_returned_or_stopped) return false;   // hiện riêng trong cột "Trả hàng"
            let val = so[field];
            if (dim === 'delivery_status' && val === 'unshipped') val = 'pending';
            if (dim === 'packing_status') {
                // Màn hình kiểm soát đóng gói chỉ quan tâm đơn chưa giao.
                if (so.real_delivery_status === 'full') return false;
                // Shipper đã nhận → "Đang giao" (ưu tiên cao nhất)
                if (so.has_shipper_received) val = 'shipping';
                // Đã in nhưng có phiếu mới chưa in → "Có phiếu chưa in"
                if (so.has_new_unprinted_pickings) val = 'has_unprinted';
                // Đã đóng gói đủ → giữ nguyên, không bị đè bởi printed_waiting
                else if (val === 'fully_packed') { /* giữ nguyên */ }
                // Đã in tất cả phiếu, chờ đóng gói → "Đã in, chờ đóng gói"
                else if (so.picking_slip_printed) val = 'printed_waiting';
                // Đã đóng gói đủ nhưng shipper chưa nhận → "Đã gói, chờ nhận giao"
                // Gom nhóm để tập trung hành động: còn hàng chưa đóng = cần xử lý ngay.
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

    async loadMoreKanbanBatch() {
        if (this.state.isLoading || !this.hasMoreKanbanData) return;
        this.state.kanbanBatchSize += 200;
        await this.fetchData();
    }

    // --- Returned / Stopped orders group ---
    get returnedOrders() {
        return this.state.saleOrders.filter(so => so.is_returned_or_stopped);
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

    async printSelectedPickingSlips() {
        if (this.selectedCount === 0) return;

        const selectedIds = Array.from(this.state.selectedSOIds);

        try {
            this.state.isLoading = true;

            // Luôn gọi giữ hàng (check availability) trước khi in
            // Backend sẽ tự xác định picking nào chưa assigned để reserve
            try {
                const reserveResponse = await fetch('/hlv_sale_delivery_planning/reserve_stock', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        method: 'call',
                        params: { sale_order_ids: selectedIds },
                    }),
                });
                const reserveResult = await reserveResponse.json();
                if (reserveResult.result) {
                    console.log('Giữ hàng:', reserveResult.result.message);
                }
            } catch (reserveErr) {
                console.warn('Giữ hàng thất bại, tiếp tục in:', reserveErr);
            }

            const url = `/hlv_sale_delivery_planning/print_picking_slips`;
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: JSON.stringify({
                    jsonrpc: '2.0',
                    method: 'call',
                    params: {
                        sale_order_ids: selectedIds,
                    },
                }),
            });

            const result = await response.json();
            if (result.error) {
                console.error('Error printing picking slips:', result.error);
                alert('Lỗi khi in phiếu lấy hàng: ' + (result.error.data?.message || result.error.message));
                return;
            }

            if (result.result && result.result.success === false) {
                alert(result.result.message || 'Không thể in phiếu lấy hàng');
                return;
            }

            // Open PDF in new tab
            if (result.result && result.result.url) {
                window.open(result.result.url, '_blank');
                // Đánh dấu ribbon "Đã in" trên các đơn vừa in (optimistic update)
                for (const so of this.state.saleOrders) {
                    if (selectedIds.includes(so.id)) {
                        so.picking_slip_printed = true;
                        so.has_new_unprinted_pickings = false;
                    }
                }
                // Clear selections after successful print
                this.clearAllSelections();
            }
        } catch (error) {
            console.error('Error printing picking slips:', error);
            alert('Lỗi khi in phiếu lấy hàng');
        } finally {
            this.state.isLoading = false;
        }
    }

    // --- Drag & Drop Handlers ---
    onDragStart(ev, soId) {
        this.state.draggedSoId = soId;
        ev.dataTransfer.effectAllowed = 'move';
        ev.dataTransfer.setData('text/plain', String(soId));
    }

    onDragOver(ev, colValue) {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = 'move';
        if (this.state.dragOverColumn !== colValue) {
            this.state.dragOverColumn = colValue;
        }
    }

    onDragLeave(ev) {
        // Chỉ xóa highlight khi thực sự rời khỏi column (không phải trượt qua child)
        if (!ev.currentTarget.contains(ev.relatedTarget)) {
            this.state.dragOverColumn = null;
        }
    }

    onDrop(ev, colValue) {
        ev.preventDefault();
        const soId = parseInt(ev.dataTransfer.getData('text/plain'), 10);
        if (!soId) return;

        const dim = this.state.kanbanGroupBy;
        const fieldMap = {
            delivery_status: 'real_delivery_status',
            stock_status:    'stock_status',
            packing_status:  'packing_status',
        };
        const field = fieldMap[dim];

        // Cập nhật state cục bộ (optimistic update)
        const so = this.state.saleOrders.find(s => s.id === soId);
        if (so) {
            so[field] = colValue;
        }

        // Đưa card lên đầu cột đích
        const existingOrder = (this.state.kanbanColumnOrder[colValue] || []).filter(id => id !== soId);
        this.state.kanbanColumnOrder[colValue] = [soId, ...existingOrder];

        this.state.draggedSoId = null;
        this.state.dragOverColumn = null;
    }

    onDragEnd() {
        this.state.draggedSoId = null;
        this.state.dragOverColumn = null;
    }

    async setStockFilter(status) {
        if (this.state.filterStockStatus === status) {
            // Nếu click lại chính Tab đó thì bỏ lọc (Về Tất Cả)
            this.state.filterStockStatus = 'all';
        } else {
            this.state.filterStockStatus = status;
        }
        this.state.currentPage = 1;
        await this.fetchData();
    }

    async setPackingFilter(status) {
        if (this.state.filterPackingStatus === status) {
            this.state.filterPackingStatus = 'all';
        } else {
            this.state.filterPackingStatus = status;
        }
        this.state.currentPage = 1;
        await this.fetchData();
    }

    async onSearchKeyup(ev) {
        if (ev.key === "Enter") {
            this.state.currentPage = 1;
            this.state.selectedSOIds = new Set();
            await this.fetchData();
        }
    }

    async onTagFilterChange(ev) {
        this.state.filterTagIds = Array.from(ev.target.selectedOptions)
            .map(o => parseInt(o.value))
            .filter(v => !isNaN(v));
        this.state.currentPage = 1;
        this.state.selectedSOIds = new Set();
        await this.fetchData();
    }

    // Odoo crm.tag color integer → background color
    getTagColor(colorInt) {
        const COLORS = [
            '#adb5bd', // 0 grey
            '#dc3545', // 1 red
            '#fd7e14', // 2 orange
            '#ffc107', // 3 yellow
            '#20c997', // 4 teal
            '#6610f2', // 5 indigo
            '#d63384', // 6 pink
            '#0d6efd', // 7 blue
            '#6f42c1', // 8 purple
            '#e91e63', // 9 fuchsia
            '#198754', // 10 green
            '#0dcaf0', // 11 cyan
        ];
        return COLORS[colorInt] || COLORS[0];
    }

    getTagTextColor(colorInt) {
        // Dark text for light backgrounds (yellow, teal, cyan), white for others
        return [3, 4, 11].includes(colorInt) ? '#000' : '#fff';
    }

    openSaleOrder(soId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: soId,
            views: [[false, "form"]],
            target: "new",
        });
    }

    openPurchaseOrder(poId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "purchase.order",
            res_id: poId,
            views: [[false, "form"]],
            target: "new",
        });
    }

    openPicking(pickingId) {
        this.state.printMenuPickingId = null;
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            res_id: pickingId,
            views: [[false, "form"]],
            target: "new",
        });
    }

    togglePickingPrintMenu(ev, pickingId) {
        ev.stopPropagation();
        this.state.printMenuPickingId =
            this.state.printMenuPickingId === pickingId ? null : pickingId;
    }

    async doPrintPickingReport(ev, pickingId, reportId) {
        ev.stopPropagation();
        this.state.printMenuPickingId = null;
        await this.actionService.doAction(reportId, {
            additionalContext: {
                active_ids: [pickingId],
                active_id: pickingId,
                active_model: 'stock.picking',
            }
        });
    }

    openVideo(url) {
        window.open(url, '_blank');
    }

    // --- PO Status Formatting (Receipt Based) ---
    getPOStatusClass(receiptStatus) {
        switch (receiptStatus) {
            case "pending": return "bg-secondary";
            case "partial": return "bg-warning text-dark";
            case "full":    return "bg-success";
            default:        return "bg-light text-muted border";
        }
    }

    // --- Translations (delegate to utils) ---
    translatePOStatus(s)         { return translatePOStatus(s); }
    translateDeliveryStatus(s)   { return translateDeliveryStatus(s); }
    translatePickingState(s)     { return translatePickingState(s); }
    translatePickingStatus(s)    { return translatePickingStatus(s); }
    translateStockStatus(s)      { return translateStockStatus(s); }
    translatePackingStatus(s)    { return translatePackingStatus(s); }
    translateSOStatus(s)         { return translateSOStatus(s); }

    formatPackageGroupStatus(so, group) {
        if (group.picking_state !== 'done') {
            return this.translatePickingState(group.picking_state);
        }

        // Logic: Nếu có bất kỳ kiện nào trong group đã đến 'Partners/Customers' -> "Đã giao khách"
        const hasDeliveredPack = (group.packages || []).some(p =>
            (p.location_name || "").includes("Partners/Customers")
        );

        if (hasDeliveredPack) {
            return "Đã giao khách";
        }

        // Nếu là phiếu đóng gói xong or phiếu OUT xong mà chưa giao đến khách -> "Đã đóng gói" 
        const lowerName = (group.picking_name || "").toLowerCase();
        if (lowerName.includes("pack") || lowerName.includes("đóng gói") || lowerName.includes("đầu ra")) {
            return "Đã đóng gói";
        }

        return "Hoàn thành";
    }

    getPackageGroupBadgeClass(so, group) {
        if (group.picking_state !== 'done') {
            return this.getPickingStateBadgeClass(group.picking_state);
        }

        const status = this.formatPackageGroupStatus(so, group);
        if (status === "Đã giao khách") {
            return "bg-success text-bg-success"; // Green
        }
        if (status === "Đã đóng gói") {
            return "bg-info text-bg-info"; // Blue
        }
        return "bg-primary text-bg-primary"; // Hoàn thành default
    }

    toggleSection(sectionKey) {
        if (this.state.collapsedSections.has(sectionKey)) {
            this.state.collapsedSections.delete(sectionKey);
        } else {
            this.state.collapsedSections.add(sectionKey);
        }
    }

    isSectionCollapsed(sectionKey) {
        return this.state.collapsedSections.has(sectionKey);
    }

    // --- Badge Classes (delegate to utils) ---
    getPickingStateBadgeClass(s)            { return getPickingStateBadgeClass(s); }
    getPickingStatusBadgeClass(s)           { return getPickingStatusBadgeClass(s); }
    getDeliveryStatusBadgeClass(s)          { return getDeliveryStatusBadgeClass(s); }
    getStockStatusBadgeClass(s)             { return getStockStatusBadgeClass(s); }
    getPackingStatusBadgeClass(s)           { return getPackingStatusBadgeClass(s); }
    getPOStatusBadgeClass(state, receipt)   { return getPOStatusBadgeClass(state, receipt); }
    getSOCardColorClass(so)                 { return getSOCardColorClass(so); }

    // --- Formatting (delegate to utils) ---
    formatCurrency(v)                       { return formatCurrency(v); }
    formatQty(v)                            { return formatQty(v); }
    getDatesComparisonClass(soDate, poDate) { return getDatesComparisonClass(soDate, poDate); }

    // --- Group duplicate product lines ---
    groupedLines(lines) {
        if (!lines || !lines.length) return [];
        const map = {};
        const order = [];
        for (const l of lines) {
            const pid = l.product_id ? l.product_id[0] : 0;
            if (map[pid]) {
                map[pid].product_uom_qty += (l.product_uom_qty || 0);
                map[pid].qty_delivered += (l.qty_delivered || 0);
                map[pid].qty_reserved_here += (l.qty_reserved_here || 0); // sum across lines
                // qty_warehouse_free: keep first (product-level, same for all lines of same product/wh)
            } else {
                map[pid] = { ...l, product_uom_qty: l.product_uom_qty || 0,
                    qty_delivered: l.qty_delivered || 0, qty_packed: l.qty_packed || 0,
                    qty_available: l.qty_available || 0, qty_warehouse_free: l.qty_warehouse_free || 0,
                    qty_reserved_here: l.qty_reserved_here || 0 };
                order.push(pid);
            }
        }
        return order.map(pid => map[pid]);
    }

    // --- Hover Interactions cho Liên kết Return/Backorder ---
    onPickingHover(pickingName) {
        const safeName = pickingName.split('/').join('-');

        // Highlight chính nó và các node con (Các phiếu return từ nó)
        const childNodes = document.querySelectorAll(`.linked-return-${safeName}`);
        childNodes.forEach(node => {
            node.classList.add('shadow', 'border-warning', 'bg-warning', 'bg-opacity-10');
            node.style.transform = 'scale(1.05)';
        });

        // Nếu nó bè Phiếu Con (return_of / backorder_of) -> Highlight Thẻ Cha 
        const pickingElement = document.querySelector(`[data-picking-name="${safeName}"]`);
        if (pickingElement) {
            // Check nếu chính thẻ này là thẻ con (có return_of)
            const parentClassMatches = Array.from(pickingElement.classList).find(cls => cls.startsWith('linked-return-'));
            if (parentClassMatches) {
                const parentName = parentClassMatches.replace('linked-return-', '');
                const parentNode = document.querySelector(`.original-picking-${parentName}`);
                if (parentNode) {
                    parentNode.classList.add('shadow', 'border-warning', 'bg-warning', 'bg-opacity-10');
                    parentNode.style.transform = 'scale(1.05)';
                }
            }
        }
    }

    onPickingLeave() {
        // Gỡ bỏ toàn bộ hiệu ứng Highlight
        const allHighlighted = document.querySelectorAll('.picking-node');
        allHighlighted.forEach(node => {
            node.classList.remove('shadow', 'border-warning', 'bg-warning', 'bg-opacity-10');
            node.style.transform = 'scale(1)';
        });
    }

    // --- Drawer Actions ---
    openOverviewDrawer(so) {
        this.state.selectedOrder = so;
        this.state.isDrawerOpen = true;
    }

    closeOverviewDrawer() {
        this.state.isDrawerOpen = false;
    }

    // --- Package Modal Actions
    openPackageDetails(pack) {
        this.state.selectedPackage = pack;
        this.state.isPackageModalOpen = true;
    }

    closePackageDetails() {
        this.state.isPackageModalOpen = false;
        this.state.selectedPackage = null;
    }

    // ── Transfer Modal ────────────────────────────────────────────────────

    async openTransferModal() {
        if (this.selectedCount === 0) {
            alert('Vui lòng chọn ít nhất 1 đơn hàng.');
            return;
        }
        this.state.isTransferModalOpen = true;
        this.state.transferModalLoading = true;
        this.state.transferModalData = null;
        this.state.transferSelections = {};

        try {
            const selectedIds = Array.from(this.state.selectedSOIds);
            const data = await this.orm.call(
                'sale.order',
                'prepare_transfer_modal_data',
                [],
                { sale_order_ids: selectedIds }
            );
            this.state.transferModalData = data;

            // Init selections for each warehouse (partner auto-applied from wh.partner_id)
            const selections = {};
            for (const wh of (data.warehouses || [])) {
                const prodSel = {};
                for (const prod of (wh.products || [])) {
                    prodSel[prod.product_id] = { include: true, qty: prod.total_qty };
                }
                selections[wh.warehouse_id] = {
                    selected: true,
                    partner_id: wh.partner_id || false,
                    products: prodSel,
                };
            }
            this.state.transferSelections = selections;
        } catch (err) {
            console.error('Lỗi khi tải dữ liệu luân chuyển:', err);
            alert('Lỗi khi phân tích dữ liệu luân chuyển: ' + (err.message || ''));
            this.state.isTransferModalOpen = false;
        } finally {
            this.state.transferModalLoading = false;
        }
    }

    closeTransferModal() {
        this.state.isTransferModalOpen = false;
        this.state.transferModalData = null;
        this.state.transferSelections = {};
    }

    toggleWarehouseSelection(whId, checked) {
        if (!this.state.transferSelections[whId]) return;
        this.state.transferSelections[whId].selected = checked;
        // Force OWL reactivity
        this.state.transferSelections = { ...this.state.transferSelections };
    }

    setTransferPartner(whId, partnerId) {
        if (!this.state.transferSelections[whId]) return;
        this.state.transferSelections[whId].partner_id = partnerId ? parseInt(partnerId) : '';
    }

    getProductSelection(whId, productId) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel || !whSel.products) return null;
        return whSel.products[productId] || null;
    }

    toggleProductSelection(whId, productId, checked) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel) return;
        if (!whSel.products[productId]) return;
        whSel.products[productId].include = checked;
        this.state.transferSelections = { ...this.state.transferSelections };
    }

    toggleAllProducts(whId, checked) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel) return;
        for (const pid of Object.keys(whSel.products)) {
            whSel.products[pid].include = checked;
        }
        this.state.transferSelections = { ...this.state.transferSelections };
    }

    areAllProductsSelected(whId) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel || !whSel.products) return false;
        return Object.values(whSel.products).every(p => p.include);
    }

    setProductQty(whId, productId, qty) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel || !whSel.products[productId]) return;
        whSel.products[productId].qty = qty;
    }

    countSelectedProducts(whId) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel) return 0;
        return Object.values(whSel.products || {}).filter(p => p.include).length;
    }

    sumSelectedQty(whId) {
        const whSel = this.state.transferSelections[whId];
        if (!whSel) return 0;
        return Object.values(whSel.products || {})
            .filter(p => p.include)
            .reduce((s, p) => s + (p.qty || 0), 0);
    }

    exportTransferExcel() {
        const selectedIds = Array.from(this.state.selectedSOIds);
        if (!selectedIds.length) return;
        const params = new URLSearchParams();
        params.set('sale_order_ids', JSON.stringify(selectedIds));
        window.open(`/hlv_sale_delivery_planning/export_transfer_excel?${params.toString()}`, '_blank');
    }

    async confirmCreateTransferPickings() {
        const data = this.state.transferModalData;
        if (!data || !data.warehouses) return;

        const warehouseSelections = [];
        for (const wh of data.warehouses) {
            const sel = this.state.transferSelections[wh.warehouse_id];
            if (!sel || !sel.selected) continue;

            const products = (wh.products || [])
                .filter(prod => {
                    const ps = sel.products[prod.product_id];
                    return ps && ps.include && ps.qty > 0;
                })
                .map(prod => ({
                    product_id: prod.product_id,
                    total_qty: sel.products[prod.product_id].qty,
                }));

            if (!products.length) continue;

            warehouseSelections.push({
                warehouse_id: wh.warehouse_id,
                picking_type_id: wh.picking_type_id,
                lot_stock_id: wh.lot_stock_id,
                transit_location_id: wh.transit_location_id,
                partner_id: sel.partner_id || false,
                products,
            });
        }

        if (!warehouseSelections.length) {
            alert('Vui lòng chọn ít nhất 1 kho và 1 sản phẩm.');
            return;
        }

        this.state.isCreatingTransfer = true;
        try {
            const result = await this.orm.call(
                'sale.order',
                'create_transfer_pickings',
                [],
                { warehouse_selections: warehouseSelections }
            );

            const created = result.created || [];
            const errors = result.errors || [];

            if (created.length) {
                const names = created.map(c => c.picking_name).join(', ');
                const msg = `Đã tạo ${created.length} phiếu luân chuyển: ${names}`;
                alert(msg);
                this.closeTransferModal();
                await this.fetchData();
            }

            if (errors.length) {
                const errMsg = errors.map(e => `Kho ${e.warehouse_id}: ${e.error}`).join('\n');
                alert('Lỗi khi tạo phiếu:\n' + errMsg);
            }
        } catch (err) {
            console.error('Lỗi tạo phiếu luân chuyển:', err);
            alert('Lỗi: ' + (err.message || ''));
        } finally {
            this.state.isCreatingTransfer = false;
        }
    }

    async printPackageLabel(pack) {
        if (!pack || !pack.picking_id) return;

        await this.actionService.doAction("hlv_pack_sequence.action_report_package_labels", {
            additionalContext: {
                active_ids: [pack.picking_id],
                active_model: 'stock.picking'
            },
        });
    }

    formatPackageLocation(locationName) {
        if (!locationName) {
            return "khu vực đóng gói";
        }
        if (locationName.includes("Partners/Customers")) {
            return "đã giao khách";
        }
        if (locationName.includes("/OUT") || locationName.includes("Đầu ra")) {
            return "chờ xuất kho";
        }
        return locationName;
    }

    // --- Filter Helpers ---
    get hasActiveFilters() {
        return this.state.searchQuery ||
            this.state.filterWarehouseId !== "all" ||
            this.state.filterDeliveryStatus !== "all" ||
            this.state.filterStockStatus !== "all" ||
            this.state.filterDateFrom ||
            this.state.filterDateTo ||
            this.state.filterPODateFrom ||
            this.state.filterPODateTo ||
            this.state.filterPOStatus !== "all" ||
            this.state.filterPackingStatus !== "all" ||
            this.state.filterSalerCode ||
            this.state.filterHtgh ||
            this.state.filterDeliveryType !== "all" ||
            this.state.filterTagIds.length > 0 ||
            this.state.showCompleted;
    }

    saveHtghPreset() {
        const val = this.state.filterHtgh.trim();
        if (!val) return;
        const label = prompt('Tên gợi ý:', val.slice(0, 30));
        if (!label) return;
        this.state.htghPresets = [...this.state.htghPresets, { label, value: val }];
        localStorage.setItem('hlv_htgh_presets', JSON.stringify(this.state.htghPresets));
    }

    removeHtghPreset(idx) {
        this.state.htghPresets = this.state.htghPresets.filter((_, i) => i !== idx);
        localStorage.setItem('hlv_htgh_presets', JSON.stringify(this.state.htghPresets));
    }

    countTransferWarehouses(so) {
        if (!so.transfer_suggestions) return 0;
        const whIds = {};
        so.transfer_suggestions.forEach(s => (s.sources || []).forEach(src => { whIds[src.from_warehouse_id] = 1; }));
        return Object.keys(whIds).length;
    }

    resetFilters() {
        this.state.searchQuery = "";
        this.state.filterWarehouseId = "all";
        this.state.filterDeliveryStatus = "all";
        this.state.filterStockStatus = "all";
        this.state.filterDateFrom = "";
        this.state.filterDateTo = null;
        this.state.filterPODateFrom = null;
        this.state.filterPODateTo = null;
        this.state.filterPOStatus = "all";
        this.state.filterPackingStatus = "all";
        this.state.filterSalerCode = "";
        this.state.filterHtgh = "";
        this.state.filterDeliveryType = "all";
        this.state.filterTagIds = [];
        this.state.filterNeedTransfer = false;
        this.state.showCompleted = false;
        this.state.currentPage = 1;
        this.fetchData();
    }

    exportExcel() {
        const params = new URLSearchParams({
            search_query: this.state.searchQuery.trim(),
            filter_warehouse_id: this.state.filterWarehouseId,
            filter_delivery_status: this.state.filterDeliveryStatus,
            filter_stock_status: this.state.filterStockStatus,
            filter_packing_status: this.state.filterPackingStatus,
            filter_date_from: this.state.filterDateFrom || '',
            filter_date_to: this.state.filterDateTo || '',
            filter_po_date_from: this.state.filterPODateFrom || '',
            filter_po_date_to: this.state.filterPODateTo || '',
            filter_po_status: this.state.filterPOStatus,
            filter_saler_code: this.state.filterSalerCode.trim(),
            filter_htgh: this.state.filterHtgh.trim(),
            filter_delivery_type: this.state.filterDeliveryType,
            filter_tag_ids: this.state.filterTagIds.join(','),
            show_completed: this.state.showCompleted ? '1' : '',
        });
        window.open(`/hlv_sale_delivery_planning/export_excel?${params.toString()}`, '_blank');
    }

    // ── Relocation Modal (Chuyển vị trí) ────────────────────────────────

    async openRelocationModal() {
        if (this.selectedCount === 0) {
            alert('Vui lòng chọn ít nhất 1 đơn hàng.');
            return;
        }
        this.state.isRelocationModalOpen = true;
        this.state.relocationModalLoading = true;
        this.state.relocationModalData = null;
        this.state.relocationOrderSelections = {};
        this.state.relocationSaveDefault = false;

        try {
            const selectedIds = Array.from(this.state.selectedSOIds);

            // Giữ hàng (reserve) trước khi lấy dữ liệu chuyển vị trí — giống luồng in phiếu
            try {
                const reserveResponse = await fetch('/hlv_sale_delivery_planning/reserve_stock', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    },
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        method: 'call',
                        params: { sale_order_ids: selectedIds },
                    }),
                });
                const reserveResult = await reserveResponse.json();
                if (reserveResult.result) {
                    console.log('Giữ hàng trước chuyển vị trí:', reserveResult.result.message);
                }
            } catch (reserveErr) {
                console.warn('Giữ hàng thất bại, tiếp tục:', reserveErr);
            }
            const data = await this.orm.call(
                'sale.order',
                'prepare_relocation_data',
                [],
                { sale_order_ids: selectedIds }
            );
            this.state.relocationModalData = data;
            this.state.relocationDestLocationId = data.default_dest_location_id || null;

            // Init selections cho mỗi đơn
            const selections = {};
            for (const order of (data.orders || [])) {
                const prodSel = {};
                for (const prod of (order.products || [])) {
                    prodSel[prod.product_id] = { include: true, qty: prod.pending_qty };
                }
                selections[order.sale_order_id] = {
                    selected: true,
                    products: prodSel,
                };
            }
            this.state.relocationOrderSelections = selections;
        } catch (err) {
            console.error('Lỗi khi tải dữ liệu chuyển vị trí:', err);
            alert('Lỗi: ' + (err.message || ''));
            this.state.isRelocationModalOpen = false;
        } finally {
            this.state.relocationModalLoading = false;
        }
    }

    closeRelocationModal() {
        this.state.isRelocationModalOpen = false;
        this.state.relocationModalData = null;
        this.state.relocationOrderSelections = {};
    }

    toggleRelocationOrder(soId, checked) {
        if (!this.state.relocationOrderSelections[soId]) return;
        this.state.relocationOrderSelections[soId].selected = checked;
        this.state.relocationOrderSelections = { ...this.state.relocationOrderSelections };
    }

    getRelocationProductSel(soId, productId) {
        const oSel = this.state.relocationOrderSelections[soId];
        if (!oSel || !oSel.products) return null;
        return oSel.products[productId] || null;
    }

    toggleRelocationProduct(soId, productId, checked) {
        const oSel = this.state.relocationOrderSelections[soId];
        if (!oSel || !oSel.products[productId]) return;
        oSel.products[productId].include = checked;
        this.state.relocationOrderSelections = { ...this.state.relocationOrderSelections };
    }

    setRelocationProductQty(soId, productId, qty) {
        const oSel = this.state.relocationOrderSelections[soId];
        if (!oSel || !oSel.products[productId]) return;
        oSel.products[productId].qty = parseFloat(qty) || 0;
    }

    async confirmCreateRelocationPickings() {
        const destLocId = parseInt(this.state.relocationDestLocationId);
        if (!destLocId) {
            alert('Vui lòng chọn vị trí đích.');
            return;
        }

        const orders = [];
        for (const order of (this.state.relocationModalData?.orders || [])) {
            const oSel = this.state.relocationOrderSelections[order.sale_order_id];
            if (!oSel || !oSel.selected) continue;

            const products = (order.products || [])
                .filter(p => {
                    const ps = oSel.products[p.product_id];
                    return ps && ps.include && ps.qty > 0;
                })
                .map(p => ({
                    product_id: p.product_id,
                    qty: oSel.products[p.product_id].qty,
                }));

            if (!products.length) continue;
            orders.push({
                sale_order_id: order.sale_order_id,
                products,
            });
        }

        if (!orders.length) {
            alert('Vui lòng chọn ít nhất 1 đơn hàng và sản phẩm.');
            return;
        }

        this.state.isCreatingRelocation = true;
        try {
            const result = await this.orm.call(
                'sale.order',
                'create_relocation_pickings',
                [],
                {
                    relocation_data: {
                        dest_location_id: destLocId,
                        save_as_default: this.state.relocationSaveDefault,
                        orders,
                    },
                }
            );

            const created = result.created || [];
            const errors = result.errors || [];

            if (created.length) {
                const names = created.map(c => `${c.sale_order_name}: ${c.picking_name}`).join('\n');
                alert(`Đã tạo ${created.length} phiếu chuyển vị trí:\n${names}`);
                // Mở PDF phiếu chuyển vị trí (nếu có)
                if (result.pdf_url) {
                    window.open(result.pdf_url, '_blank');
                }
                this.closeRelocationModal();
                await this.fetchData();
            }

            if (errors.length) {
                const errMsg = errors.map(e => e.error).join('\n');
                alert('Lỗi:\n' + errMsg);
            }
        } catch (err) {
            console.error('Lỗi tạo phiếu chuyển vị trí:', err);
            alert('Lỗi: ' + (err.message || ''));
        } finally {
            this.state.isCreatingRelocation = false;
        }
    }
}

registry.category("actions").add("hlv_sale_delivery_planning.dashboard", DeliveryPlannerDashboard);
