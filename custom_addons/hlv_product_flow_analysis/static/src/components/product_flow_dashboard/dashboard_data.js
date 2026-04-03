/** @odoo-module **/

/**
 * Data management mixins: filtered/sorted/paginated data, pagination handlers,
 * export, navigation, formatting helpers.
 */
export const dashboardDataMixins = {
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
    },

    get filteredProducts() {
        const all = this.allFilteredProducts;
        const start = (this.state.productPage - 1) * this.state.productPageSize;
        return all.slice(start, start + this.state.productPageSize);
    },

    get productTotalPages() {
        return Math.max(1, Math.ceil(this.allFilteredProducts.length / this.state.productPageSize));
    },

    get productTotalFiltered() {
        return this.allFilteredProducts.length;
    },

    get allFilteredSuppliers() {
        let items = this.state.suppliers;
        const q = this.state.supplierSearch;
        if (q) {
            items = items.filter(s => s.partner_name.toLowerCase().includes(q));
        }
        return this._sortItems(items, this.state.supplierSortField, this.state.supplierSortAsc);
    },

    get filteredSuppliers() {
        const all = this.allFilteredSuppliers;
        const start = (this.state.supplierPage - 1) * this.state.supplierPageSize;
        return all.slice(start, start + this.state.supplierPageSize);
    },

    get supplierTotalPages() {
        return Math.max(1, Math.ceil(this.allFilteredSuppliers.length / this.state.supplierPageSize));
    },

    get supplierTotalFiltered() {
        return this.allFilteredSuppliers.length;
    },

    get allFilteredPlanning() {
        let items = this.state.planning;
        const q = this.state.planningSearch;
        if (q) {
            items = items.filter(p =>
                p.product_name.toLowerCase().includes(q) ||
                (p.default_code && p.default_code.toLowerCase().includes(q))
            );
        }
        if (!this.state.planningShowAll) {
            const minFreq = this.state.planningMinFrequency || 3;
            items = items.filter(p => (p.total_frequency || 0) >= minFreq);
        }
        return this._sortItems(items, this.state.planningSortField, this.state.planningSortAsc);
    },

    get filteredPlanning() {
        const all = this.allFilteredPlanning;
        const start = (this.state.planningPage - 1) * this.state.planningPageSize;
        return all.slice(start, start + this.state.planningPageSize);
    },

    get planningTotalPages() {
        return Math.max(1, Math.ceil(this.allFilteredPlanning.length / this.state.planningPageSize));
    },

    get planningTotalFiltered() {
        return this.allFilteredPlanning.length;
    },

    // ========== Pagination ==========
    onProductPageSizeChange(ev) {
        this.state.productPageSize = parseInt(ev.target.value);
        this.state.productPage = 1;
    },
    productPrevPage() { if (this.state.productPage > 1) this.state.productPage--; },
    productNextPage() { if (this.state.productPage < this.productTotalPages) this.state.productPage++; },

    onSupplierPageSizeChange(ev) {
        this.state.supplierPageSize = parseInt(ev.target.value);
        this.state.supplierPage = 1;
    },
    supplierPrevPage() { if (this.state.supplierPage > 1) this.state.supplierPage--; },
    supplierNextPage() { if (this.state.supplierPage < this.supplierTotalPages) this.state.supplierPage++; },

    onPlanningPageSizeChange(ev) {
        this.state.planningPageSize = parseInt(ev.target.value);
        this.state.planningPage = 1;
    },
    planningPrevPage() { if (this.state.planningPage > 1) this.state.planningPage--; },
    planningNextPage() { if (this.state.planningPage < this.planningTotalPages) this.state.planningPage++; },

    getPageStart(tab) {
        if (tab === "products") return (this.state.productPage - 1) * this.state.productPageSize;
        if (tab === "suppliers") return (this.state.supplierPage - 1) * this.state.supplierPageSize;
        return (this.state.planningPage - 1) * this.state.planningPageSize;
    },

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
    },

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
    },

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
    },

    // ========== Supplier expand ==========
    toggleSupplier(partnerId) {
        this.state.expandedSupplier =
            this.state.expandedSupplier === partnerId ? null : partnerId;
    },

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
    },

    closeTrend() {
        this.state.showTrend = false;
    },

    // ========== Navigation ==========
    openProduct(productId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "product.product",
            res_id: productId,
            views: [[false, "form"]],
            target: "current",
        });
    },

    openSupplier(partnerId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: partnerId,
            views: [[false, "form"]],
            target: "current",
        });
    },

    // ========== Helpers ==========
    formatNumber(num) {
        if (num === undefined || num === null) return "0";
        return Number(num).toLocaleString("vi-VN", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
    },

    formatCurrency(num) {
        if (num === undefined || num === null) return "0 ₫";
        return Number(num).toLocaleString("vi-VN", { minimumFractionDigits: 0, maximumFractionDigits: 0 }) + " ₫";
    },

    getStatusClass(status) {
        return { danger: "pf-status-danger", warning: "pf-status-warning", ok: "pf-status-ok" }[status] || "pf-status-ok";
    },

    getStatusLabel(status) {
        return { danger: "Cần nhập gấp", warning: "Sắp hết", ok: "Đủ hàng" }[status] || "Đủ hàng";
    },

    getTrendBarHeight(value, maxVal) {
        if (!maxVal || maxVal === 0) return "0%";
        return Math.round((value / maxVal) * 100) + "%";
    },

    get trendMaxVal() {
        if (!this.state.trendData.length) return 1;
        let max = 0;
        for (const t of this.state.trendData) {
            if (t.incoming > max) max = t.incoming;
            if (t.outgoing > max) max = t.outgoing;
        }
        return max || 1;
    },

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
    },

    getBarWidth(value, max) {
        if (!max) return "0%";
        return Math.round((value / max) * 100) + "%";
    },
};
