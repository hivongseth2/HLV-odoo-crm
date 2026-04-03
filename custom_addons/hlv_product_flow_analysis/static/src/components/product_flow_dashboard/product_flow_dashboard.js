/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class ProductFlowDashboard extends Component {
    static template = "hlv_product_flow_analysis.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            isLoading: true,
            activeTab: "products", // products | suppliers | planning
            period: "month",
            warehouseId: false,
            warehouses: [],
            // Summary
            summary: {},
            // Product flow data
            products: [],
            productSearch: "",
            productSort: "total_qty",
            productSortAsc: false,
            // Supplier data
            suppliers: [],
            supplierSearch: "",
            expandedSupplier: null,
            // Planning data
            planning: [],
            planningSearch: "",
            // Trend
            trendProductId: null,
            trendProductName: "",
            trendData: [],
            showTrend: false,
            // Date range
            dateFrom: "",
            dateTo: "",
        });

        onWillStart(async () => {
            await this.loadDashboard();
        });
    }

    async loadDashboard() {
        this.state.isLoading = true;
        try {
            const params = this._getParams();
            const summary = await this.orm.call(
                "product.flow.analysis",
                "get_dashboard_summary",
                [],
                params
            );
            this.state.summary = summary;
            this.state.warehouses = summary.warehouses || [];
            this.state.dateFrom = summary.date_from;
            this.state.dateTo = summary.date_to;

            // Load tab-specific data
            await this.loadTabData();
        } catch (e) {
            this.notification.add("Lỗi tải dữ liệu: " + (e.message || e), {
                type: "danger",
            });
        }
        this.state.isLoading = false;
    }

    async loadTabData() {
        const params = this._getParams();
        if (this.state.activeTab === "products") {
            const result = await this.orm.call(
                "product.flow.analysis",
                "get_product_flow_data",
                [],
                params
            );
            this.state.products = result.products || [];
        } else if (this.state.activeTab === "suppliers") {
            const result = await this.orm.call(
                "product.flow.analysis",
                "get_supplier_flow_data",
                [],
                params
            );
            this.state.suppliers = result.suppliers || [];
        } else if (this.state.activeTab === "planning") {
            const result = await this.orm.call(
                "product.flow.analysis",
                "get_inventory_planning_data",
                [],
                params
            );
            this.state.planning = result.planning || [];
        }
    }

    _getParams() {
        return {
            period: this.state.period,
            date_from: this.state.dateFrom || false,
            date_to: this.state.dateTo || false,
            warehouse_id: this.state.warehouseId || false,
        };
    }

    // --- Tab switching ---
    switchTab(tab) {
        if (this.state.activeTab !== tab) {
            this.state.activeTab = tab;
            this.state.showTrend = false;
            this.loadTabData();
        }
    }

    // --- Period change ---
    async onPeriodChange(ev) {
        this.state.period = ev.target.value;
        this.state.dateFrom = "";
        this.state.dateTo = "";
        await this.loadDashboard();
    }

    // --- Warehouse change ---
    async onWarehouseChange(ev) {
        const val = ev.target.value;
        this.state.warehouseId = val === "all" ? false : parseInt(val);
        await this.loadDashboard();
    }

    // --- Custom date range ---
    async onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
        if (this.state.dateFrom && this.state.dateTo) {
            this.state.period = "custom";
            await this.loadDashboard();
        }
    }

    async onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
        if (this.state.dateFrom && this.state.dateTo) {
            this.state.period = "custom";
            await this.loadDashboard();
        }
    }

    // --- Search filters ---
    onProductSearch(ev) {
        this.state.productSearch = ev.target.value.toLowerCase();
    }

    onSupplierSearch(ev) {
        this.state.supplierSearch = ev.target.value.toLowerCase();
    }

    onPlanningSearch(ev) {
        this.state.planningSearch = ev.target.value.toLowerCase();
    }

    // --- Filtered data getters ---
    get filteredProducts() {
        let items = this.state.products;
        const q = this.state.productSearch;
        if (q) {
            items = items.filter(
                (p) =>
                    p.product_name.toLowerCase().includes(q) ||
                    (p.default_code && p.default_code.toLowerCase().includes(q))
            );
        }
        return items;
    }

    get filteredSuppliers() {
        let items = this.state.suppliers;
        const q = this.state.supplierSearch;
        if (q) {
            items = items.filter((s) =>
                s.partner_name.toLowerCase().includes(q)
            );
        }
        return items;
    }

    get filteredPlanning() {
        let items = this.state.planning;
        const q = this.state.planningSearch;
        if (q) {
            items = items.filter(
                (p) =>
                    p.product_name.toLowerCase().includes(q) ||
                    (p.default_code && p.default_code.toLowerCase().includes(q))
            );
        }
        return items;
    }

    // --- Supplier expand ---
    toggleSupplier(partnerId) {
        this.state.expandedSupplier =
            this.state.expandedSupplier === partnerId ? null : partnerId;
    }

    // --- Product trend ---
    async showProductTrend(productId, productName) {
        this.state.trendProductId = productId;
        this.state.trendProductName = productName;
        try {
            const trends = await this.orm.call(
                "product.flow.analysis",
                "get_trend_data",
                [productId, 6]
            );
            this.state.trendData = trends;
            this.state.showTrend = true;
        } catch (e) {
            this.notification.add("Lỗi tải trend: " + (e.message || e), {
                type: "danger",
            });
        }
    }

    closeTrend() {
        this.state.showTrend = false;
    }

    // --- Navigate to product form ---
    openProduct(productId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "product.product",
            res_id: productId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // --- Navigate to supplier form ---
    openSupplier(partnerId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: partnerId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // --- Helpers ---
    formatNumber(num) {
        if (num === undefined || num === null) return "0";
        return Number(num).toLocaleString("vi-VN", {
            minimumFractionDigits: 0,
            maximumFractionDigits: 2,
        });
    }

    formatCurrency(num) {
        if (num === undefined || num === null) return "0 ₫";
        return (
            Number(num).toLocaleString("vi-VN", {
                minimumFractionDigits: 0,
                maximumFractionDigits: 0,
            }) + " ₫"
        );
    }

    getPeriodLabel() {
        const labels = {
            week: "Tuần này",
            month: "Tháng này",
            quarter: "Quý này",
            year: "Năm nay",
            custom: "Tùy chọn",
        };
        return labels[this.state.period] || "Tháng này";
    }

    getStatusClass(status) {
        return {
            danger: "pf-status-danger",
            warning: "pf-status-warning",
            ok: "pf-status-ok",
        }[status] || "pf-status-ok";
    }

    getStatusLabel(status) {
        return {
            danger: "Cần nhập gấp",
            warning: "Sắp hết",
            ok: "Đủ hàng",
        }[status] || "Đủ hàng";
    }

    getTrendBarHeight(value, maxVal) {
        if (!maxVal || maxVal === 0) return "0%";
        return Math.round((value / maxVal) * 100) + "%";
    }

    get trendMaxVal() {
        if (!this.state.trendData.length) return 1;
        let max = 0;
        for (const t of this.state.trendData) {
            if (t.incoming > max) max = t.incoming;
            if (t.outgoing > max) max = t.outgoing;
        }
        return max || 1;
    }
}

registry
    .category("actions")
    .add("hlv_product_flow_analysis.Dashboard", ProductFlowDashboard);
