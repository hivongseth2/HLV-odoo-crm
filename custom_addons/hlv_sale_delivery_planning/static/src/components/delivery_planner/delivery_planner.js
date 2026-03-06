/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

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
            filterDeliveryStatus: "all",
            filterStockStatus: "all",
            filterDateFrom: "",
            filterDateTo: "",
            filterPODateFrom: "",
            filterPODateTo: "",
            filterPOStatus: "all",

            // Stats
            dashboardStats: { total: 0, ready: 0, partial: 0, out_of_stock: 0 },

            // Pagination
            currentPage: 1,
            itemsPerPage: 12,
            totalCount: 0,

            // Drawer
            isDrawerOpen: false,
            selectedOrder: null,
        });

        onWillStart(async () => {
            await this.fetchData();
        });
    }

    async fetchData() {
        this.state.isLoading = true;
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
                    limit: this.state.itemsPerPage,
                    offset: (this.state.currentPage - 1) * this.state.itemsPerPage,
                }
            );

            this.state.dashboardStats = result.dashboard_stats || { total: 0, ready: 0, partial: 0, out_of_stock: 0 };
            const fetchedOrders = result.orders || [];
            this.state.saleOrders = fetchedOrders.map(so => {
                so.flows = so.flows || [];
                so.pickings = so.pickings || [];
                so.lines = so.lines || [];
                so.pos = so.pos || [];
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
        await this.fetchData();
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
            case "pending":
                return "bg-secondary"; // Chưa nhận
            case "partial":
                return "bg-warning text-dark"; // Nhận 1 phần
            case "full":
                return "bg-success"; // Nhận đủ
            default:
                return "bg-light text-muted border";
        }
    }

    translatePOStatus(receiptStatus) {
        const trans = {
            partial: "Nhận 1 phần",
            pending: "Chưa nhận",
            full: "Đã nhận đủ",
            unknown: "Không rõ"
        };
        return trans[receiptStatus] || "Mới Tạo / Hủy";
    }

    // --- Translations ---
    translateDeliveryStatus(status) {
        const trans = {
            'unknown': 'Chưa cập nhật',
            'pending': 'Chưa giao',
            'partial': 'Giao 1 phần',
            'pending_partial': 'Chưa & Giao 1 phần',
            'full': 'Đã giao đủ'
        };
        return trans[status] || (status ? status.toUpperCase() : '');
    }

    translateStockStatus(status) {
        const trans = {
            'out_of_stock': 'Không có hàng',
            'partial_ready': 'Có hàng 1 phần',
            'ready': 'Đủ hàng xuất'
        };
        return trans[status] || (status ? status.toUpperCase() : '');
    }

    translateSOStatus(status) {
        const trans = {
            'draft': 'Báo giá',
            'sent': 'Đã gửi',
            'sale': 'Đơn hàng',
            'done': 'Khóa',
            'cancel': 'Đã hủy',
        };
        return trans[status] || (status ? status.toUpperCase() : '');
    }

    translatePickingStatus(state) {
        const trans = {
            'draft': 'Nháp',
            'waiting': 'Chờ QĐ',
            'confirmed': 'Chờ hàng',
            'assigned': 'Sẵn sàng',
            'done': 'Hoàn thành',
            'cancel': 'Hủy'
        };
        return trans[state] || (state ? state.toUpperCase() : '');
    }

    getPOStatusBadgeClass(state, receiptStatus) {
        if (state === 'cancel') return 'text-bg-secondary';
        if (receiptStatus === 'full') return 'text-bg-success';
        if (receiptStatus === 'partial') return 'text-bg-info';
        if (state === 'purchase' || state === 'done') return 'text-bg-primary';
        return 'text-bg-light border text-dark';
    }

    getDeliveryStatusBadgeClass(status) {
        if (status === 'full') return 'text-bg-success';
        if (status === 'partial') return 'text-bg-warning';
        if (status === 'pending') return 'text-bg-secondary';
        return 'text-bg-light border text-dark';
    }

    getStockStatusBadgeClass(status) {
        if (status === 'ready') return 'text-bg-primary';
        if (status === 'partial_ready') return 'text-bg-warning';
        if (status === 'out_of_stock') return 'text-bg-danger';
        return 'text-bg-light border text-dark';
    }

    getPickingStatusBadgeClass(state) {
        if (state === 'done') return 'text-bg-success';
        if (state === 'assigned') return 'text-bg-primary';
        if (state === 'cancel') return 'text-bg-secondary opacity-50';
        return 'text-bg-warning';
    }

    getDatesComparisonClass(soDate, poDate) {
        if (!soDate || !poDate) return '';
        const so = new Date(soDate);
        const po = new Date(poDate);
        if (po > so) return 'text-danger fw-bold';
        return 'text-success';
    }

    formatCurrency(value) {
        return new Intl.NumberFormat('vi-VN', { style: 'currency', currency: 'VND' }).format(value);
    }

    formatQty(value) {
        return parseFloat(Number(value).toFixed(2));
    }

    getSOCardColorClass(so) {
        if (so.real_delivery_status === 'full') return 'border-success border-2 shadow-sm';
        if (so.stock_status === 'ready') return 'border-primary border-2 shadow-sm';
        if (so.stock_status === 'partial_ready') return 'border-warning border-2 shadow-sm';
        return 'border-danger border-2 shadow-sm';
    }

    // --- Drawer Actions ---
    openOverviewDrawer(so) {
        this.state.selectedOrder = so;
        this.state.isDrawerOpen = true;
    }

    closeOverviewDrawer() {
        this.state.isDrawerOpen = false;
    }
}

registry.category("actions").add("hlv_sale_delivery_planning_dashboard", DeliveryPlannerDashboard);
