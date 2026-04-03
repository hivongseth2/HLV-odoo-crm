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
            activeTab: "products",
            period: "month",
            warehouseId: false,
            warehouses: [],
            summary: {},
            // Product flow
            products: [],
            productSearch: "",
            productSortField: "incoming_count",
            productSortAsc: false,
            productMinCount: 0,
            // Pagination - products
            productPage: 1,
            productPageSize: 20,
            // Supplier
            suppliers: [],
            supplierSearch: "",
            supplierSortField: "total_qty",
            supplierSortAsc: false,
            expandedSupplier: null,
            // Pagination - suppliers
            supplierPage: 1,
            supplierPageSize: 20,
            // Planning
            planning: [],
            planningSearch: "",
            planningSortField: "days_remaining",
            planningSortAsc: true,
            planningPage: 1,
            planningPageSize: 20,
            // Trend
            trendProductId: null,
            trendProductName: "",
            trendData: [],
            showTrend: false,
            // Date
            dateFrom: "",
            dateTo: "",
            // Export
            isExporting: false,
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
            await this.loadTabData();
        } catch (e) {
            this.notification.add("Lỗi tải dữ liệu: " + (e.message || e), { type: "danger" });
        }
        this.state.isLoading = false;
    }

    async loadTabData() {
        const params = this._getParams();
        if (this.state.activeTab === "products") {
            const result = await this.orm.call("product.flow.analysis", "get_product_flow_data", [], params);
            this.state.products = result.products || [];
            this.state.productPage = 1;
        } else if (this.state.activeTab === "suppliers") {
            const result = await this.orm.call("product.flow.analysis", "get_supplier_flow_data", [], params);
            this.state.suppliers = result.suppliers || [];
            this.state.supplierPage = 1;
        } else if (this.state.activeTab === "planning") {
            const result = await this.orm.call("product.flow.analysis", "get_inventory_planning_data", [], params);
            this.state.planning = result.planning || [];
            this.state.planningPage = 1;
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

    // ========== Tab switching ==========
    switchTab(tab) {
        if (this.state.activeTab !== tab) {
            this.state.activeTab = tab;
            this.state.showTrend = false;
            this.loadTabData();
        }
    }

    // ========== Period / Warehouse / Date ==========
    async onPeriodChange(ev) {
        this.state.period = ev.target.value;
        this.state.dateFrom = "";
        this.state.dateTo = "";
        await this.loadDashboard();
    }

    async onWarehouseChange(ev) {
        const val = ev.target.value;
        this.state.warehouseId = val === "all" ? false : parseInt(val);
        await this.loadDashboard();
    }

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

    // ========== Search ==========
    onProductSearch(ev) {
        this.state.productSearch = ev.target.value.toLowerCase();
        this.state.productPage = 1;
    }
    onSupplierSearch(ev) {
        this.state.supplierSearch = ev.target.value.toLowerCase();
        this.state.supplierPage = 1;
    }
    onPlanningSearch(ev) {
        this.state.planningSearch = ev.target.value.toLowerCase();
        this.state.planningPage = 1;
    }

    // ========== Min count filter ==========
    onMinCountChange(ev) {
        this.state.productMinCount = parseInt(ev.target.value) || 0;
        this.state.productPage = 1;
    }

    // ========== Sorting ==========
    sortProducts(field) {
        if (this.state.productSortField === field) {
            this.state.productSortAsc = !this.state.productSortAsc;
        } else {
            this.state.productSortField = field;
            this.state.productSortAsc = false;
        }
        this.state.productPage = 1;
    }

    sortSuppliers(field) {
        if (this.state.supplierSortField === field) {
            this.state.supplierSortAsc = !this.state.supplierSortAsc;
        } else {
            this.state.supplierSortField = field;
            this.state.supplierSortAsc = false;
        }
        this.state.supplierPage = 1;
    }

    sortPlanning(field) {
        if (this.state.planningSortField === field) {
            this.state.planningSortAsc = !this.state.planningSortAsc;
        } else {
            this.state.planningSortField = field;
            this.state.planningSortAsc = true;
        }
        this.state.planningPage = 1;
    }

    getSortIcon(tab, field) {
        let sortField, sortAsc;
        if (tab === "products") { sortField = this.state.productSortField; sortAsc = this.state.productSortAsc; }
        else if (tab === "suppliers") { sortField = this.state.supplierSortField; sortAsc = this.state.supplierSortAsc; }
        else { sortField = this.state.planningSortField; sortAsc = this.state.planningSortAsc; }
        if (sortField !== field) return "fa fa-sort pf-sort-inactive";
        return sortAsc ? "fa fa-sort-asc" : "fa fa-sort-desc";
    }

    _sortItems(items, field, asc) {
        return [...items].sort((a, b) => {
            let va = a[field], vb = b[field];
            if (typeof va === "string") { va = va.toLowerCase(); vb = (vb || "").toLowerCase(); }
            if (va < vb) return asc ? -1 : 1;
            if (va > vb) return asc ? 1 : -1;
            return 0;
        });
    }

    // ========== Filtered + sorted + paginated data ==========
    get allFilteredProducts() {
        let items = this.state.products;
        const q = this.state.productSearch;
        if (q) {
            items = items.filter(p =>
                p.product_name.toLowerCase().includes(q) ||
                (p.default_code && p.default_code.toLowerCase().includes(q))
            );
        }
        const minCount = this.state.productMinCount;
        if (minCount > 0) {
            items = items.filter(p => p.incoming_count >= minCount);
        }
        return this._sortItems(items, this.state.productSortField, this.state.productSortAsc);
    }

    get filteredProducts() {
        const all = this.allFilteredProducts;
        const start = (this.state.productPage - 1) * this.state.productPageSize;
        return all.slice(start, start + this.state.productPageSize);
    }

    get productTotalPages() {
        return Math.max(1, Math.ceil(this.allFilteredProducts.length / this.state.productPageSize));
    }

    get productTotalFiltered() {
        return this.allFilteredProducts.length;
    }

    get allFilteredSuppliers() {
        let items = this.state.suppliers;
        const q = this.state.supplierSearch;
        if (q) {
            items = items.filter(s => s.partner_name.toLowerCase().includes(q));
        }
        return this._sortItems(items, this.state.supplierSortField, this.state.supplierSortAsc);
    }

    get filteredSuppliers() {
        const all = this.allFilteredSuppliers;
        const start = (this.state.supplierPage - 1) * this.state.supplierPageSize;
        return all.slice(start, start + this.state.supplierPageSize);
    }

    get supplierTotalPages() {
        return Math.max(1, Math.ceil(this.allFilteredSuppliers.length / this.state.supplierPageSize));
    }

    get supplierTotalFiltered() {
        return this.allFilteredSuppliers.length;
    }

    get allFilteredPlanning() {
        let items = this.state.planning;
        const q = this.state.planningSearch;
        if (q) {
            items = items.filter(p =>
                p.product_name.toLowerCase().includes(q) ||
                (p.default_code && p.default_code.toLowerCase().includes(q))
            );
        }
        return this._sortItems(items, this.state.planningSortField, this.state.planningSortAsc);
    }

    get filteredPlanning() {
        const all = this.allFilteredPlanning;
        const start = (this.state.planningPage - 1) * this.state.planningPageSize;
        return all.slice(start, start + this.state.planningPageSize);
    }

    get planningTotalPages() {
        return Math.max(1, Math.ceil(this.allFilteredPlanning.length / this.state.planningPageSize));
    }

    get planningTotalFiltered() {
        return this.allFilteredPlanning.length;
    }

    // ========== Pagination ==========
    onProductPageSizeChange(ev) {
        this.state.productPageSize = parseInt(ev.target.value);
        this.state.productPage = 1;
    }
    productPrevPage() { if (this.state.productPage > 1) this.state.productPage--; }
    productNextPage() { if (this.state.productPage < this.productTotalPages) this.state.productPage++; }

    onSupplierPageSizeChange(ev) {
        this.state.supplierPageSize = parseInt(ev.target.value);
        this.state.supplierPage = 1;
    }
    supplierPrevPage() { if (this.state.supplierPage > 1) this.state.supplierPage--; }
    supplierNextPage() { if (this.state.supplierPage < this.supplierTotalPages) this.state.supplierPage++; }

    onPlanningPageSizeChange(ev) {
        this.state.planningPageSize = parseInt(ev.target.value);
        this.state.planningPage = 1;
    }
    planningPrevPage() { if (this.state.planningPage > 1) this.state.planningPage--; }
    planningNextPage() { if (this.state.planningPage < this.planningTotalPages) this.state.planningPage++; }

    getPageStart(tab) {
        if (tab === "products") return (this.state.productPage - 1) * this.state.productPageSize;
        if (tab === "suppliers") return (this.state.supplierPage - 1) * this.state.supplierPageSize;
        return (this.state.planningPage - 1) * this.state.planningPageSize;
    }

    // ========== Export Excel ==========
    async exportProductExcel() {
        this.state.isExporting = true;
        try {
            const params = this._getParams();
            const b64 = await this.orm.call("product.flow.analysis", "export_product_flow_excel", [], params);
            this._downloadBase64("hang_hoa_luu_thong.xlsx", b64);
            this.notification.add("Xuất Excel thành công!", { type: "success" });
        } catch (e) {
            this.notification.add("Lỗi xuất Excel: " + (e.message || e), { type: "danger" });
        }
        this.state.isExporting = false;
    }

    async exportSupplierExcel() {
        this.state.isExporting = true;
        try {
            const params = this._getParams();
            const b64 = await this.orm.call("product.flow.analysis", "export_supplier_flow_excel", [], params);
            this._downloadBase64("nha_cung_cap.xlsx", b64);
            this.notification.add("Xuất Excel thành công!", { type: "success" });
        } catch (e) {
            this.notification.add("Lỗi xuất Excel: " + (e.message || e), { type: "danger" });
        }
        this.state.isExporting = false;
    }

    _downloadBase64(filename, b64data) {
        const byteChars = atob(b64data);
        const byteNumbers = new Array(byteChars.length);
        for (let i = 0; i < byteChars.length; i++) {
            byteNumbers[i] = byteChars.charCodeAt(i);
        }
        const byteArray = new Uint8Array(byteNumbers);
        const blob = new Blob([byteArray], {
            type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    // ========== Supplier expand ==========
    toggleSupplier(partnerId) {
        this.state.expandedSupplier =
            this.state.expandedSupplier === partnerId ? null : partnerId;
    }

    // ========== Trend ==========
    async showProductTrend(productId, productName) {
        this.state.trendProductId = productId;
        this.state.trendProductName = productName;
        try {
            const trends = await this.orm.call("product.flow.analysis", "get_trend_data", [productId, 6]);
            this.state.trendData = trends;
            this.state.showTrend = true;
        } catch (e) {
            this.notification.add("Lỗi tải trend: " + (e.message || e), { type: "danger" });
        }
    }

    closeTrend() {
        this.state.showTrend = false;
    }

    // ========== Navigation ==========
    openProduct(productId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "product.product",
            res_id: productId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openSupplier(partnerId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: partnerId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ========== Helpers ==========
    formatNumber(num) {
        if (num === undefined || num === null) return "0";
        return Number(num).toLocaleString("vi-VN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
    }

    formatCurrency(num) {
        if (num === undefined || num === null) return "0 ₫";
        return Number(num).toLocaleString("vi-VN", { minimumFractionDigits: 0, maximumFractionDigits: 0 }) + " ₫";
    }

    getStatusClass(status) {
        return { danger: "pf-status-danger", warning: "pf-status-warning", ok: "pf-status-ok" }[status] || "pf-status-ok";
    }

    getStatusLabel(status) {
        return { danger: "Cần nhập gấp", warning: "Sắp hết", ok: "Đủ hàng" }[status] || "Đủ hàng";
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

registry.category("actions").add("hlv_product_flow_analysis.Dashboard", ProductFlowDashboard);
