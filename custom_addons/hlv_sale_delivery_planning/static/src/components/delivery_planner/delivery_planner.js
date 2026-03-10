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
            viewMode: 'list',               // 'list' | 'kanban'
            kanbanGroupBy: 'delivery_status', // 'delivery_status' | 'stock_status' | 'packing_status'
            draggedSoId: null,
            dragOverColumn: null,
            kanbanColumnOrder: {},           // { colValue: [soId, ...] } — thứ tự DnD client-side
            kanbanColPageSize: {},           // { colValue: N } — số card hiển thị mỗi cột
        });

        onWillStart(async () => {
            await this.fetchData();
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
                    // Kanban tải theo batch, không phân trang backend
                    limit: isKanban ? 200 : this.state.itemsPerPage,
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
                { value: 'waiting_stock',  label: 'Không Có Hàng Đóng',      badgeClass: 'bg-secondary',          textClass: 'text-secondary', iconClass: 'fa fa-hourglass-start', progressClass: 'bg-secondary' },
                { value: 'unpacked',       label: 'Có Hàng Chưa Đóng Gói',   badgeClass: 'bg-warning text-dark',  textClass: 'text-warning',   iconClass: 'fa fa-exclamation-triangle', progressClass: 'bg-warning' },
                { value: 'fully_packed',   label: 'Đã Đóng Gói Đủ',          badgeClass: 'bg-success',            textClass: 'text-success',   iconClass: 'fa fa-check-square-o', progressClass: 'bg-success' },
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

        const base = this.state.saleOrders.filter(so => {
            let val = so[field];
            if (dim === 'delivery_status' && val === 'unshipped') val = 'pending';
            if (dim === 'packing_status') {
                // Màn hình kiểm soát đóng gói chỉ quan tâm đơn chưa giao.
                if (so.real_delivery_status === 'full') return false;
                // Gom nhóm để tập trung hành động: còn hàng chưa đóng = cần xử lý ngay.
                if (val === 'partial_packed') val = 'unpacked';
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
            await this.fetchData();
        }
    }

    openSaleOrder(soId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: soId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openPurchaseOrder(poId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "purchase.order",
            res_id: poId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openPicking(pickingId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            res_id: pickingId,
            views: [[false, "form"]],
            target: "current",
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
            this.state.filterPackingStatus !== "all";
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
        this.state.currentPage = 1;
        this.fetchData();
    }
}

registry.category("actions").add("hlv_sale_delivery_planning.dashboard", DeliveryPlannerDashboard);
