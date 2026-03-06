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

            // Pagination
            currentPage: 1,
            itemsPerPage: 12,

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
                []
            );
            this.state.saleOrders = result.orders || [];
            this.state.warehouses = result.warehouses || [];
            this.state.currentPage = 1; // Reset to page 1 on fetch
        } catch (error) {
            console.error("Lỗi khi tải dữ liệu bảng điều phối:", error);
        } finally {
            this.state.isLoading = false;
        }
    }

    // --- Computed Filters & Pagination ---
    get filteredOrders() {
        let list = this.state.saleOrders;
        const query = this.state.searchQuery.toLowerCase().trim();

        // 1. Text Search
        if (query) {
            list = list.filter(so =>
                so.name.toLowerCase().includes(query) ||
                (so.partner_id && so.partner_id[1].toLowerCase().includes(query))
            );
        }

        // 2. Warehouse Filter (Lọc theo kho của Picking)
        if (this.state.filterWarehouseId !== "all") {
            const wId = parseInt(this.state.filterWarehouseId);
            list = list.filter(so => so.picking_warehouse_ids && so.picking_warehouse_ids.includes(wId));
        }

        // 3. Tiến Độ Giao Hàng
        if (this.state.filterDeliveryStatus !== "all") {
            list = list.filter(so => so.real_delivery_status === this.state.filterDeliveryStatus);
        }

        // 4. Tình Trạng Kho
        if (this.state.filterStockStatus === "ready") {
            list = list.filter(so => so.is_fully_ready && so.real_delivery_status !== 'full');
        } else if (this.state.filterStockStatus === "pending") {
            list = list.filter(so => !so.is_fully_ready && so.real_delivery_status !== 'full');
        }

        // 4. Date Filters (Hẹn Giao - nếu không có lấy Ngày Đặt Hàng)
        if (this.state.filterDateFrom) {
            const dFrom = new Date(this.state.filterDateFrom);
            list = list.filter(so => {
                const dDate = so.commitment_date ? new Date(so.commitment_date) : (so.date_order ? new Date(so.date_order) : null);
                return dDate && dDate >= dFrom;
            });
        }

        if (this.state.filterDateTo) {
            const dTo = new Date(this.state.filterDateTo);
            dTo.setHours(23, 59, 59, 999);
            list = list.filter(so => {
                const dDate = so.commitment_date ? new Date(so.commitment_date) : (so.date_order ? new Date(so.date_order) : null);
                return dDate && dDate <= dTo;
            });
        }

        return list;
    }

    get totalPages() {
        return Math.ceil(this.filteredOrders.length / this.state.itemsPerPage) || 1;
    }

    get paginatedOrders() {
        const start = (this.state.currentPage - 1) * this.state.itemsPerPage;
        const end = start + this.state.itemsPerPage;
        return this.filteredOrders.slice(start, end);
    }

    // --- Actions ---
    nextPage() {
        if (this.state.currentPage < this.totalPages) {
            this.state.currentPage++;
        }
    }

    prevPage() {
        if (this.state.currentPage > 1) {
            this.state.currentPage--;
        }
    }

    onFilterChange() {
        this.state.currentPage = 1; // reset page on filter
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

    // --- Translations ---
    translateDeliveryStatus(status) {
        const trans = {
            'unknown': 'Chưa cập nhật',
            'pending': 'Chưa giao',
            'partial': 'Giao 1 phần',
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

    translatePOStatus(status) {
        const trans = {
            'draft': 'Nháp',
            'sent': 'Đã gửi',
            'to approve': 'Chờ duyệt',
            'purchase': 'Đơn Mua',
            'done': 'Khóa',
            'cancel': 'Đã hủy',
            'pending': 'Chờ nhận',
            'partial': 'Nhận 1 phần',
            'full': 'Đã nhận đủ'
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
        if (state === 'cancel') return 'text-bg-secondary';
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
        this.state.selectedOrder = null;
    }
}

registry.category("actions").add("hlv_sale_delivery_planning.dashboard", DeliveryPlannerDashboard);
