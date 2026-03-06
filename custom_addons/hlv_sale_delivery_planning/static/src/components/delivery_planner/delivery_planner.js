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
            filterStatus: "all", // all, ready, pending

            // Pagination
            currentPage: 1,
            itemsPerPage: 12,
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

        // 2. Warehouse Filter
        if (this.state.filterWarehouseId !== "all") {
            const wId = parseInt(this.state.filterWarehouseId);
            list = list.filter(so => so.warehouse_id && so.warehouse_id[0] === wId);
        }

        // 3. Status Filter (Đã đủ hàng vs Còn thiếu)
        if (this.state.filterStatus === "ready") {
            list = list.filter(so => so.is_fully_ready);
        } else if (this.state.filterStatus === "pending") {
            list = list.filter(so => !so.is_fully_ready);
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

    getPOStatusBadgeClass(state, receiptStatus) {
        if (state === 'cancel') return 'text-bg-secondary';
        if (receiptStatus === 'full') return 'text-bg-success';
        if (receiptStatus === 'partial') return 'text-bg-warning';
        if (state === 'purchase' || state === 'done') return 'text-bg-info';
        return 'text-bg-light text-dark';
    }

    getSOStatusBadgeClass(deliveryStatus) {
        if (deliveryStatus === 'full') return 'text-bg-success';
        if (deliveryStatus === 'partial') return 'text-bg-warning';
        return 'text-bg-info';
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
}

registry.category("actions").add("hlv_sale_delivery_planning.dashboard", DeliveryPlannerDashboard);
