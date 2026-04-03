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
            // Charts panel
            chartsPanelOpen: false,
            chartsActiveSection: 'products',
            // Planning frequency filter
            planningMinFrequency: 3,
            planningShowAll: false,
        });

        onWillStart(async () => {
            await this.loadDashboard();
        });
    }

    async loadDashboard() {
        this.state.isLoading = true;
        try {
            const params = this._getParams();
            const [summary, productResult, supplierResult] = await Promise.all([
                this.orm.call("product.flow.analysis", "get_dashboard_summary", [], params),
                this.orm.call("product.flow.analysis", "get_product_flow_data", [], params),
                this.orm.call("product.flow.analysis", "get_supplier_flow_data", [], params),
            ]);
            this.state.summary = summary;
            this.state.warehouses = summary.warehouses || [];
            this.state.dateFrom = summary.date_from;
            this.state.dateTo = summary.date_to;
            this.state.products = productResult.products || [];
            this.state.productPage = 1;
            this.state.suppliers = supplierResult.suppliers || [];
            this.state.supplierPage = 1;
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

    // ========== Charts panel ==========
    toggleChartsPanel() {
        this.state.chartsPanelOpen = !this.state.chartsPanelOpen;
    }

    setChartsSection(section) {
        this.state.chartsActiveSection = section;
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

    // ========== Planning frequency filter ==========
    onPlanningMinFreqChange(ev) {
        this.state.planningMinFrequency = parseInt(ev.target.value) || 3;
        this.state.planningPage = 1;
    }

    togglePlanningShowAll() {
        this.state.planningShowAll = !this.state.planningShowAll;
        this.state.planningPage = 1;
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
        // Frequency-based filter: chỉ ưu tiên SP hay mua bán
        if (!this.state.planningShowAll) {
            const minFreq = this.state.planningMinFrequency || 3;
            items = items.filter(p => (p.total_frequency || 0) >= minFreq);
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

    // ========== Heat-map helpers ==========
    getHeatClass(value, field) {
        const products = this.state.products;
        if (!products.length || !value) return "";
        const vals = products.map(p => p[field] || 0).filter(v => v > 0);
        if (!vals.length) return "";
        const max = Math.max(...vals);
        const ratio = value / max;
        if (ratio >= 0.75) return "pf-heat-4";
        if (ratio >= 0.5) return "pf-heat-3";
        if (ratio >= 0.25) return "pf-heat-2";
        if (value > 0) return "pf-heat-1";
        return "";
    }

    // ========== Chart computed data ==========
    get topPurchasedProducts() {
        return [...this.state.products]
            .filter(p => p.incoming_qty > 0)
            .sort((a, b) => b.incoming_qty - a.incoming_qty)
            .slice(0, 8);
    }

    get topSoldProducts() {
        return [...this.state.products]
            .filter(p => p.outgoing_qty > 0)
            .sort((a, b) => b.outgoing_qty - a.outgoing_qty)
            .slice(0, 8);
    }

    get topPurchasedMax() {
        const items = this.topPurchasedProducts;
        return items.length ? items[0].incoming_qty : 1;
    }

    get topSoldMax() {
        const items = this.topSoldProducts;
        return items.length ? items[0].outgoing_qty : 1;
    }

    get slowMovingProducts() {
        return [...this.state.products]
            .filter(p => p.qty_available > 0 && p.outgoing_qty === 0 && p.avg_storage_days > 14)
            .sort((a, b) => b.avg_storage_days - a.avg_storage_days)
            .slice(0, 5);
    }

    get fastMovingProducts() {
        return [...this.state.products]
            .filter(p => p.outgoing_count > 0)
            .sort((a, b) => b.outgoing_count - a.outgoing_count)
            .slice(0, 5);
    }

    get purchaseRecommendations() {
        // Sản phẩm bán nhiều nhưng tồn kho thấp → nên mua thêm
        return [...this.state.products]
            .filter(p => {
                if (p.outgoing_qty <= 0) return false;
                // Tỷ lệ bán/tồn cao → cần mua
                const ratio = p.qty_available > 0 ? p.outgoing_qty / p.qty_available : 999;
                return ratio > 0.5;
            })
            .map(p => {
                const ratio = p.qty_available > 0 ? p.outgoing_qty / p.qty_available : 999;
                let urgency = "ok";
                if (ratio > 3) urgency = "danger";
                else if (ratio > 1) urgency = "warning";
                const suggestQty = Math.max(0, Math.round(p.outgoing_qty * 1.2 - p.qty_available));
                return { ...p, ratio: Math.round(ratio * 100) / 100, urgency, suggestQty };
            })
            .sort((a, b) => b.ratio - a.ratio)
            .slice(0, 10);
    }

    get stockDistribution() {
        const products = this.state.products;
        let overstock = 0, healthy = 0, low = 0, outOfStock = 0;
        for (const p of products) {
            if (p.qty_available <= 0) outOfStock++;
            else if (p.outgoing_qty > 0 && p.qty_available < p.outgoing_qty * 0.3) low++;
            else if (p.outgoing_qty > 0 && p.qty_available > p.outgoing_qty * 3) overstock++;
            else healthy++;
        }
        const total = products.length || 1;
        return {
            overstock: { count: overstock, pct: Math.round(overstock / total * 100) },
            healthy: { count: healthy, pct: Math.round(healthy / total * 100) },
            low: { count: low, pct: Math.round(low / total * 100) },
            outOfStock: { count: outOfStock, pct: Math.round(outOfStock / total * 100) },
        };
    }

    getBarWidth(value, max) {
        if (!max) return "0%";
        return Math.round((value / max) * 100) + "%";
    }

    // ========== Supplier-Product Heatmap ==========
    get supplierProductHeatmap() {
        const suppliers = [...this.state.suppliers]
            .sort((a, b) => b.total_qty - a.total_qty)
            .slice(0, 10);
        // Collect all unique products across top suppliers
        const productMap = new Map();
        for (const s of suppliers) {
            for (const p of (s.products || []).slice(0, 8)) {
                if (!productMap.has(p.product_id)) {
                    productMap.set(p.product_id, { id: p.product_id, name: p.default_code || p.product_name.substring(0, 12) });
                }
            }
        }
        const products = [...productMap.values()].slice(0, 12);
        // Build matrix
        let maxQty = 1;
        const rows = suppliers.map(s => {
            const prodQtyMap = {};
            for (const p of s.products || []) {
                prodQtyMap[p.product_id] = p.qty;
                if (p.qty > maxQty) maxQty = p.qty;
            }
            return {
                supplierName: s.partner_name,
                cells: products.map(pr => ({ productId: pr.id, qty: prodQtyMap[pr.id] || 0 })),
            };
        });
        return { products, rows, maxQty };
    }

    getHeatmapCellClass(qty, maxQty) {
        if (!qty || qty <= 0) return 'pf-hm-0';
        const ratio = qty / maxQty;
        if (ratio >= 0.75) return 'pf-hm-4';
        if (ratio >= 0.5) return 'pf-hm-3';
        if (ratio >= 0.25) return 'pf-hm-2';
        return 'pf-hm-1';
    }

    // ========== Supplier chart computed data ==========
    get topSuppliersByQty() {
        return [...this.state.suppliers]
            .filter(s => s.total_qty > 0)
            .sort((a, b) => b.total_qty - a.total_qty)
            .slice(0, 8);
    }

    get topSuppliersByQtyMax() {
        const items = this.topSuppliersByQty;
        return items.length ? items[0].total_qty : 1;
    }

    get topSuppliersByAmount() {
        return [...this.state.suppliers]
            .filter(s => s.total_amount > 0)
            .sort((a, b) => b.total_amount - a.total_amount)
            .slice(0, 8);
    }

    get topSuppliersByAmountMax() {
        const items = this.topSuppliersByAmount;
        return items.length ? items[0].total_amount : 1;
    }

    get topSuppliersByFrequency() {
        return [...this.state.suppliers]
            .filter(s => s.move_count > 0)
            .sort((a, b) => b.move_count - a.move_count)
            .slice(0, 8);
    }

    get topSuppliersByFrequencyMax() {
        const items = this.topSuppliersByFrequency;
        return items.length ? items[0].move_count : 1;
    }

    get supplierConcentration() {
        const suppliers = [...this.state.suppliers].sort((a, b) => b.total_amount - a.total_amount);
        const totalAmount = suppliers.reduce((sum, s) => sum + s.total_amount, 0);
        if (!totalAmount || !suppliers.length) return { top1: 0, top3: 0, top5: 0, total: 0, count: 0 };
        const top1 = suppliers.length >= 1 ? Math.round(suppliers[0].total_amount / totalAmount * 100) : 0;
        const top3 = Math.round(suppliers.slice(0, 3).reduce((s, x) => s + x.total_amount, 0) / totalAmount * 100);
        const top5 = Math.round(suppliers.slice(0, 5).reduce((s, x) => s + x.total_amount, 0) / totalAmount * 100);
        return {
            top1,
            top3,
            top5,
            total: totalAmount,
            count: suppliers.length,
            top1Name: suppliers.length >= 1 ? suppliers[0].partner_name : '',
        };
    }

    // ========== Buy-Sell Correlation (Scatter) ==========
    get buySellCorrelation() {
        const products = this.state.products.filter(p => p.incoming_qty > 0 || p.outgoing_qty > 0);
        if (!products.length) return { points: [], maxBuy: 1, maxSell: 1, quadrants: { priority: 0, overstock: 0, supplyRisk: 0, lowActivity: 0 }, total: 0 };

        const maxBuy = Math.max(...products.map(p => p.incoming_qty)) || 1;
        const maxSell = Math.max(...products.map(p => p.outgoing_qty)) || 1;
        const buyMedian = maxBuy * 0.3;
        const sellMedian = maxSell * 0.3;

        let priority = 0, overstock = 0, supplyRisk = 0, lowActivity = 0;
        const points = products.map(p => {
            const buyPct = Math.round((p.incoming_qty / maxBuy) * 100);
            const sellPct = Math.round((p.outgoing_qty / maxSell) * 100);
            let quadrant;
            if (p.incoming_qty >= buyMedian && p.outgoing_qty >= sellMedian) {
                quadrant = 'priority'; priority++;
            } else if (p.incoming_qty >= buyMedian && p.outgoing_qty < sellMedian) {
                quadrant = 'overstock'; overstock++;
            } else if (p.incoming_qty < buyMedian && p.outgoing_qty >= sellMedian) {
                quadrant = 'supplyRisk'; supplyRisk++;
            } else {
                quadrant = 'lowActivity'; lowActivity++;
            }
            return {
                product_id: p.product_id,
                name: p.default_code || p.product_name.substring(0, 15),
                fullName: p.product_name,
                buyQty: p.incoming_qty,
                sellQty: p.outgoing_qty,
                buyPct: Math.max(buyPct, 2),
                sellPct: Math.max(sellPct, 2),
                quadrant,
            };
        });
        // Sort by total activity for display, limit to top 40
        points.sort((a, b) => (b.buyQty + b.sellQty) - (a.buyQty + a.sellQty));
        return {
            points: points.slice(0, 40),
            maxBuy, maxSell,
            quadrants: { priority, overstock, supplyRisk, lowActivity },
            total: products.length,
        };
    }

    getCorrelationPointStyle(point) {
        return `left:${point.buyPct}%;bottom:${point.sellPct}%`;
    }

    getCorrelationPointClass(point) {
        return 'pf-scatter-dot pf-q-' + point.quadrant;
    }

    // Priority level helpers for planning
    getPriorityClass(level) {
        return { high: 'pf-priority-high', medium: 'pf-priority-medium', low: 'pf-priority-low' }[level] || 'pf-priority-low';
    }

    getPriorityLabel(level) {
        return { high: 'Cao', medium: 'TB', low: 'Thấp' }[level] || 'Thấp';
    }
}

registry.category("actions").add("hlv_product_flow_analysis.Dashboard", ProductFlowDashboard);
