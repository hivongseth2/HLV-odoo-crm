/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { dashboardDataMixins } from "./dashboard_data";
import { productChartMixins } from "./chart_products";
import { supplierChartMixins } from "./chart_suppliers";
import { correlationChartMixins } from "./chart_correlation";
import { trendChartMixins } from "./chart_trend";
import { analysisChartMixins } from "./chart_analysis";
import { drilldownMixins } from "./drilldown";

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
            products: [],
            productSearch: "",
            productSortField: "incoming_count",
            productSortAsc: false,
            productMinCount: 0,
            productPage: 1,
            productPageSize: 20,
            suppliers: [],
            supplierSearch: "",
            supplierSortField: "total_qty",
            supplierSortAsc: false,
            expandedSupplier: null,
            supplierPage: 1,
            supplierPageSize: 20,
            planning: [],
            planningSearch: "",
            planningSortField: "days_remaining",
            planningSortAsc: true,
            planningPage: 1,
            planningPageSize: 20,
            trendProductId: null,
            trendProductName: "",
            trendData: [],
            showTrend: false,
            dateFrom: "",
            dateTo: "",
            isExporting: false,
            chartsPanelOpen: false,
            chartsActiveSection: 'products',
            planningMinFrequency: 3,
            planningShowAll: false,
            topN: 10,
            trendMonthly: [],
            // Product detail modal
            showProductDetail: false,
            productDetailId: null,
            productDetailName: "",
            productDetailLoading: false,
            productDetailData: { purchase_records: [], sale_records: [] },
            // AI Analysis
            aiLoading: false,
            aiAnalysis: "",
            aiError: "",
            aiStats: null,
            aiModel: "",
            aiTokens: {},
        });

        onWillStart(async () => {
            this._initDrilldown();
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
            this.state.trendMonthly = [];
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

    toggleChartsPanel() { this.state.chartsPanelOpen = !this.state.chartsPanelOpen; }
    setChartsSection(section) {
        this.state.chartsActiveSection = section;
        if (section === 'trend' && this.state.trendMonthly.length === 0) {
            this.loadTrendData();
        }
    }

    switchTab(tab) {
        if (this.state.activeTab !== tab) {
            this.state.activeTab = tab;
            this.state.showTrend = false;
            this.loadTabData();
        }
    }

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

    onProductSearch(ev) { this.state.productSearch = ev.target.value.toLowerCase(); this.state.productPage = 1; }
    onSupplierSearch(ev) { this.state.supplierSearch = ev.target.value.toLowerCase(); this.state.supplierPage = 1; }
    onPlanningSearch(ev) { this.state.planningSearch = ev.target.value.toLowerCase(); this.state.planningPage = 1; }
    onMinCountChange(ev) { this.state.productMinCount = parseInt(ev.target.value) || 0; this.state.productPage = 1; }
    onPlanningMinFreqChange(ev) { this.state.planningMinFrequency = parseInt(ev.target.value) || 3; this.state.planningPage = 1; }
    togglePlanningShowAll() { this.state.planningShowAll = !this.state.planningShowAll; this.state.planningPage = 1; }
    onTopNChange(ev) { this.state.topN = parseInt(ev.target.value) || 10; }

    sortProducts(field) {
        if (this.state.productSortField === field) { this.state.productSortAsc = !this.state.productSortAsc; }
        else { this.state.productSortField = field; this.state.productSortAsc = false; }
        this.state.productPage = 1;
    }

    sortSuppliers(field) {
        if (this.state.supplierSortField === field) { this.state.supplierSortAsc = !this.state.supplierSortAsc; }
        else { this.state.supplierSortField = field; this.state.supplierSortAsc = false; }
        this.state.supplierPage = 1;
    }

    sortPlanning(field) {
        if (this.state.planningSortField === field) { this.state.planningSortAsc = !this.state.planningSortAsc; }
        else { this.state.planningSortField = field; this.state.planningSortAsc = true; }
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
}

// Apply mixins (preserves getters via property descriptors)
const mixins = [dashboardDataMixins, productChartMixins, supplierChartMixins, correlationChartMixins, trendChartMixins, analysisChartMixins, drilldownMixins];
for (const mixin of mixins) {
    Object.defineProperties(
        ProductFlowDashboard.prototype,
        Object.getOwnPropertyDescriptors(mixin)
    );
}

registry.category("actions").add("hlv_product_flow_analysis.Dashboard", ProductFlowDashboard);
