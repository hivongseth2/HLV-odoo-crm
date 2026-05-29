// Format tiền VND
formatMoneyVND(val) {
    if (val === null || val === undefined || isNaN(val)) return '';
    return Number(val).toLocaleString('vi-VN', { style: 'currency', currency: 'VND', maximumFractionDigits: 2 });
}

// Format ngày UTC+7
formatDateVN(dateStr) {
    if (!dateStr) return '';
    let d, m, y;
    if (dateStr.includes('/')) {
        [d, m, y] = dateStr.split('/').map(Number);
        const dt = new Date(Date.UTC(y, m - 1, d, 7, 0, 0));
        return dt.toLocaleDateString('vi-VN');
    } else if (dateStr.includes('-')) {
        [y, m, d] = dateStr.split('-').map(Number);
        const dt = new Date(Date.UTC(y, m - 1, d, 7, 0, 0));
        return dt.toLocaleDateString('vi-VN');
    }
    return dateStr;
}

    // Reset manual avg cost về mặc định
    async resetManualAvgCost(productId) {
    this.state.manualAvgCosts = Object.assign({}, this.state.manualAvgCosts, { [productId]: undefined });
    await this.persistManualOverrides(productId);
    await this.toggleCellPanel(productId, 'avg_cost');
}
/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, markup } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class StockQuickView extends Component {
    static template = "hlv_inventory_group_report.StockQuickView";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        // UTC+7 default dates
        const _nowUtc7 = new Date(new Date().getTime() + 7 * 3600 * 1000);
        const _today = _nowUtc7.toISOString().slice(0, 10);
        const _firstDay = _today.slice(0, 7) + "-01";
        this.state = useState({
            groups: [],
            warehouses: [],
            groupId: false,
            warehouseIds: [],
            showZero: false,
            lines: [],
            columns: [],
            total: 0,
            loading: false,
            whOpen: false,
            // Quan ly nhom
            activeTab: "stock",
            addingGroup: false,
            newGroupName: "",
            editingGroupId: false,
            editGroupName: "",
            // Quan ly san pham trong nhom
            groupProducts: [],
            productQuery: "",
            productResults: [],
            productLoading: false,
            locationData: {},
            expandedProductId: false,
            importResults: null,
            importLoading: false,
            productPage: 0,
            productTotalCount: 0,
            includeOutgoing: true,
            outgoingTotal: 0,
            extraCols: [],
            colsOpen: false,
            infoPanel: null,
            cellPanel: null,
            cellPanelData: {},
            manualLayerAmounts: {},
            manualAvgCosts: {},
            movesData: {},
            expandedMovesId: false,
            movesDateFrom: _firstDay,
            movesDateTo: _today,
            movesExporting: false,
        });

        onWillStart(async () => {
            const ctx = this.props.action?.context || {};
            const [groups, warehouses] = await Promise.all([
                this.orm.searchRead(
                    "hlv.product.report.group",
                    [["active", "=", true]],
                    ["id", "name"],
                    { order: "sequence, name" }
                ),
                this.orm.searchRead(
                    "stock.warehouse", [],
                    ["id", "name"],
                    { order: "name" }
                ),
            ]);
            this.state.groups = groups;
            this.state.warehouses = warehouses;
            // Mac dinh chon tat ca kho de hien cot theo tung kho
            this.state.warehouseIds = warehouses.map(w => w.id);
            if (ctx.default_group_id) {
                this.state.groupId = ctx.default_group_id;
            } else if (groups.length > 0) {
                this.state.groupId = groups[0].id;
            }
            if (this.state.groupId) {
                await this.loadData();
            }
        });
    }

    async loadGroups() {
        const groups = await this.orm.searchRead(
            "hlv.product.report.group",
            [["active", "=", true]],
            ["id", "name"],
            { order: "sequence, name" }
        );
        this.state.groups = groups;
        return groups;
    }

    async loadData() {
        if (!this.state.groupId) {
            this.state.lines = [];
            this.state.columns = [];
            this.state.total = 0;
            return;
        }
        this.state.loading = true;
        try {
            const _fixedKeys = ["avg_cost", "incoming_qty", "reserved_qty"];
            const _allExtraCols = [...new Set([..._fixedKeys, ...this.state.extraCols])];
            const result = await this.orm.call(
                "hlv.stock.quick", "get_data",
                [this.state.groupId, this.state.warehouseIds, this.state.showZero, this.state.includeOutgoing, _allExtraCols]
            );
            const restoredManualAvgCosts = Object.assign({}, this.state.manualAvgCosts);
            this.state.lines = result.lines.map((line) => {
                const extra = Object.assign({}, line.extra || {});
                if (extra.manual_avg_override === true && extra.avg_cost !== undefined && extra.avg_cost !== null) {
                    restoredManualAvgCosts[line.id] = Number(extra.avg_cost);
                    extra.avg_cost = Number(extra.avg_cost);
                }
                return Object.assign({}, line, { extra });
            });
            this.state.manualAvgCosts = restoredManualAvgCosts;
            this.state.columns = result.columns;
            this.state.total = result.total;
            this.state.outgoingTotal = result.outgoing_total || 0;
        } finally {
            this.state.loading = false;
        }
    }

    selectGroup(id) {
        this.state.groupId = id;
        this.state.warehouseIds = this.state.warehouses.map(w => w.id);
        this.state.whOpen = false;
        this.state.activeTab = "stock";
        this.state.editingGroupId = false;
        this.state.productQuery = "";
        this.state.productResults = [];
        this.state.productPage = 0;
        this.state.productTotalCount = 0;
        this.state.locationData = {};
        this.state.expandedProductId = false;
        this.state.importResults = null;
        this.loadData();
    }

    setTab(tab) {
        this.state.activeTab = tab;
        if (tab === "manage" && this.state.groupId) {
            this.loadGroupProducts();
        }
    }

    // ── CRUD Nhom ──

    startAddGroup() {
        this.state.addingGroup = true;
        this.state.newGroupName = "";
    }

    cancelAddGroup() {
        this.state.addingGroup = false;
        this.state.newGroupName = "";
    }

    onAddGroupKeydown(ev) {
        if (ev.key === "Enter") { this.confirmAddGroup(); }
        if (ev.key === "Escape") { this.cancelAddGroup(); }
    }

    async confirmAddGroup() {
        const name = this.state.newGroupName.trim();
        if (!name) return;
        const ids = await this.orm.create("hlv.product.report.group", [{ name, sequence: 10 }]);
        this.state.addingGroup = false;
        await this.loadGroups();
        this.selectGroup(ids[0]);
    }

    startEditGroup(id, name) {
        this.state.editingGroupId = id;
        this.state.editGroupName = name;
    }

    cancelEditGroup() {
        this.state.editingGroupId = false;
        this.state.editGroupName = "";
    }

    onEditGroupKeydown(ev) {
        if (ev.key === "Enter") { this.confirmRenameGroup(); }
        if (ev.key === "Escape") { this.cancelEditGroup(); }
    }

    async confirmRenameGroup() {
        const id = this.state.editingGroupId;
        const name = this.state.editGroupName.trim();
        if (!name || !id) return;
        await this.orm.write("hlv.product.report.group", [id], { name });
        this.state.editingGroupId = false;
        await this.loadGroups();
    }

    async deleteGroup(id) {
        if (!window.confirm("X\u00f3a nh\u00f3m n\u00e0y? H\u00e0nh \u0111\u1ed9ng kh\u00f4ng th\u1ec3 ho\u00e0n t\u00e1c.")) return;
        await this.orm.unlink("hlv.product.report.group", [id]);
        const groups = await this.loadGroups();
        if (this.state.groupId === id) {
            if (groups.length > 0) {
                this.selectGroup(groups[0].id);
            } else {
                this.state.groupId = false;
                this.state.warehouseIds = this.state.warehouses.map(w => w.id);
                this.state.lines = [];
                this.state.columns = [];
                this.state.total = 0;
            }
        }
    }

    // ── Quan ly san pham trong nhom ──

    async loadGroupProducts() {
        if (!this.state.groupId) return;
        const result = await this.orm.call(
            "hlv.stock.quick", "get_group_products", [this.state.groupId]
        );
        this.state.groupProducts = result;
    }

    onProductQueryKeydown(ev) {
        if (ev.key === "Enter") { this.searchProducts(); }
    }

    async searchProducts(pageOrEvent) {
        const query = this.state.productQuery.trim();
        if (!query) return;
        const page = (typeof pageOrEvent === "number") ? pageOrEvent : 0;
        this.state.productPage = page;
        this.state.productLoading = true;
        try {
            const excludeIds = this.state.groupProducts.map(p => p.id);
            const result = await this.orm.call(
                "hlv.stock.quick", "search_products", [query, excludeIds, page * 50]
            );
            this.state.productResults = result.items;
            this.state.productTotalCount = result.total;
        } finally {
            this.state.productLoading = false;
        }
    }

    searchProductsPrev() {
        if (this.state.productPage > 0) {
            this.searchProducts(this.state.productPage - 1);
        }
    }

    searchProductsNext() {
        const maxPage = Math.ceil(this.state.productTotalCount / 50) - 1;
        if (this.state.productPage < maxPage) {
            this.searchProducts(this.state.productPage + 1);
        }
    }

    async addProductToGroup(productId) {
        await this.orm.write("hlv.product.report.group", [this.state.groupId], {
            product_ids: [[4, productId]],
        });
        await this.loadGroupProducts();
        this.state.productResults = this.state.productResults.filter(p => p.id !== productId);
        if (this.state.productTotalCount > 0) {
            this.state.productTotalCount -= 1;
        }
        if (this.state.productResults.length === 0 && this.state.productPage > 0) {
            this.searchProducts(this.state.productPage - 1);
        }
        this.loadData();
    }

    async removeProductFromGroup(productId) {
        await this.orm.write("hlv.product.report.group", [this.state.groupId], {
            product_ids: [[3, productId]],
        });
        await this.loadGroupProducts();
        this.loadData();
    }

    // ── Kho ──

    get warehouseSummary() {
        const n = this.state.warehouseIds.length;
        const total = this.state.warehouses.length;
        if (n === 0 || n === total) return "T\u1ea5t c\u1ea3 kho";
        if (n === 1) {
            const wh = this.state.warehouses.find(w => w.id === this.state.warehouseIds[0]);
            return wh ? wh.name : "1 kho";
        }
        return n + " kho \u0111\u00e3 ch\u1ecdn";
    }

    isWhSelected(id) {
        return this.state.warehouseIds.includes(id);
    }

    toggleWarehouse(id) {
        if (this.isWhSelected(id)) {
            this.state.warehouseIds = this.state.warehouseIds.filter(x => x !== id);
        } else {
            this.state.warehouseIds = [...this.state.warehouseIds, id];
        }
        this.loadData();
    }

    toggleAllWarehouses() {
        if (this.state.warehouseIds.length === this.state.warehouses.length) {
            this.state.warehouseIds = [];
        } else {
            this.state.warehouseIds = this.state.warehouses.map(w => w.id);
        }
        this.loadData();
    }

    toggleWhDropdown() {
        this.state.whOpen = !this.state.whOpen;
    }

    closeDropdown() {
        this.state.whOpen = false;
        this.state.colsOpen = false;
        this.state.infoPanel = null;
        this.state.cellPanel = null;
    }

    toggleInfoPanel(key) {
        this.state.infoPanel = this.state.infoPanel === key ? null : key;
    }

    closeDrawer() {
        this.state.cellPanel = null;
    }

    async toggleCellPanel(productId, key) {
        // Toggle off if same cell
        if (this.state.cellPanel && this.state.cellPanel.productId === productId && this.state.cellPanel.key === key) {
            this.state.cellPanel = null;
            return;
        }
        const line = this.state.lines.find(l => l.id === productId);
        const lineName = line ? line.name : "";
        const avgCost = (line && key === "avg_cost") ? (this.state.manualAvgCosts[productId] !== undefined ? this.state.manualAvgCosts[productId] : (line.extra && line.extra.avg_cost || 0)) : 0;
        const onHand = line ? (line.total || 0) : 0;
        this.state.cellPanel = { productId, key, lineName, avgCost, onHand };
        const cacheKey = productId + "-" + key;
        if (this.state.cellPanelData[cacheKey] !== undefined) {
            if (key === "avg_cost") {
                this.recalculateCostPanel(productId);
            }
            return;
        }
        this.state.cellPanelData = Object.assign({}, this.state.cellPanelData, { [cacheKey]: null });
        if (key === "avg_cost") {
            const result = await this.orm.call(
                "hlv.stock.quick", "get_product_cost_layers", [productId]
            );
            this.state.cellPanelData = Object.assign({}, this.state.cellPanelData, { [cacheKey]: result });
            this.recalculateCostPanel(productId);
            return;
        }
        const result = await this.orm.call(
            "hlv.stock.quick", "get_product_pending_moves",
            [productId, key, this.state.warehouseIds]
        );
        this.state.cellPanelData = Object.assign({}, this.state.cellPanelData, { [cacheKey]: result });
    }

    recalculateCostPanel(productId) {
        const cacheKey = productId + "-avg_cost";
        const panelData = this.state.cellPanelData[cacheKey];
        if (!panelData || !Array.isArray(panelData.layers)) return;

        const manualLayerAmounts = this.state.manualLayerAmounts[productId] || {};
        const recalculatedLayers = panelData.layers.map((layer) => {
            const manualAmount = manualLayerAmounts[layer.id];
            const lineQty = Number(layer.line_qty || 0);
            const allocatedQty = Number(layer.qty || 0);
            const subtotal = Number(layer.price_subtotal || 0);
            const lineTotal = Number(layer.price_total || 0);
            const taxAmount = Number(layer.price_tax || 0);

            let finalAmount = Number.isFinite(manualAmount) ? manualAmount : lineTotal;
            let appliedInternalTax = taxAmount;
            if (Number.isFinite(manualAmount)) {
                const allocatedSubtotal = subtotal * allocatedQty / (lineQty || 1);
                appliedInternalTax = Math.max(finalAmount - allocatedSubtotal, 0);
            }

            const allocatedValue = lineQty > 0 ? (finalAmount * allocatedQty / lineQty) : 0;
            const allocatedTax = lineQty > 0 ? (appliedInternalTax * allocatedQty / lineQty) : 0;
            const unitCost = lineQty > 0 ? (finalAmount / lineQty) : 0;

            return Object.assign({}, layer, {
                unit_cost: Number(unitCost.toFixed(2)),
                value: Number(allocatedValue.toFixed(2)),
                tax_value: Number(allocatedTax.toFixed(2)),
                manual_amount: Number.isFinite(manualAmount) ? Number(manualAmount.toFixed(2)) : (layer.manual_amount !== null && layer.manual_amount !== undefined ? Number(layer.manual_amount) : null),
                is_manual: Number.isFinite(manualAmount) || layer.is_manual === true,
            });
        });

        const totalQty = recalculatedLayers.reduce((sum, layer) => sum + Number(layer.qty || 0), 0);
        const totalValueFromLines = recalculatedLayers.reduce((sum, layer) => sum + Number(layer.value || 0), 0);
        const totalTax = recalculatedLayers.reduce((sum, layer) => sum + Number(layer.tax_value || 0), 0);
        const computedAvg = totalQty > 0 ? Number((totalValueFromLines / totalQty).toFixed(2)) : 0;
        const manualAvg = this.state.manualAvgCosts[productId];
        const effectiveAvg = (manualAvg !== undefined && manualAvg !== null) ? Number(manualAvg) : computedAvg;
        const totalValue = (manualAvg !== undefined && manualAvg !== null) ? Number((effectiveAvg * totalQty).toFixed(2)) : Number(totalValueFromLines.toFixed(2));

        panelData.layers = recalculatedLayers;
        panelData.total_qty = Number(totalQty.toFixed(2));
        panelData.total_value = totalValue;
        panelData.total_tax = Number(totalTax.toFixed(2));
        panelData.computed_avg = effectiveAvg;

        this.state.cellPanelData = Object.assign({}, this.state.cellPanelData, { [cacheKey]: panelData });
        this.state.cellPanel = this.state.cellPanel && this.state.cellPanel.productId === productId
            ? Object.assign({}, this.state.cellPanel, { avgCost: effectiveAvg })
            : this.state.cellPanel;

        this.state.lines = this.state.lines.map((line) => {
            if (line.id !== productId) return line;
            const extra = Object.assign({}, line.extra || {});
            extra.avg_cost = effectiveAvg;
            if (this.state.manualAvgCosts[productId] !== undefined) {
                extra.manual_avg_override = true;
            }
            return Object.assign({}, line, { extra });
        });
    }

    getLayerInputValue(layer) {
        const manualAmount = layer.manual_amount;
        const value = manualAmount !== null && manualAmount !== undefined ? manualAmount : layer.value;
        if (value === null || value === undefined) return "0.00";
        return Number(value).toFixed(2);
    }

    getManualAvgCostInput(productId) {
        const manualAvg = this.state.manualAvgCosts[productId];
        if (manualAvg !== undefined && manualAvg !== null) {
            return Number(manualAvg).toFixed(2);
        }
        const line = this.state.lines.find((l) => l.id === productId);
        const value = line && line.extra ? line.extra.avg_cost : 0;
        return Number(value || 0).toFixed(2);
    }

    async persistManualOverrides(productId) {
        const avgValue = this.state.manualAvgCosts[productId];
        const layerOverrides = Object.assign({}, this.state.manualLayerAmounts[productId] || {});
        await this.orm.call(
            "hlv.stock.quick",
            "save_manual_overrides",
            [productId, avgValue !== undefined && avgValue !== null ? Number(avgValue) : null, layerOverrides]
        );
    }

    async updateLayerManualAmount(productId, layerId, rawValue) {
        const amount = Number(rawValue);
        if (Number.isNaN(amount) || amount < 0) return;
        const productOverrides = Object.assign({}, this.state.manualLayerAmounts[productId] || {});
        productOverrides[layerId] = amount;
        this.state.manualLayerAmounts = Object.assign({}, this.state.manualLayerAmounts, { [productId]: productOverrides });
        await this.persistManualOverrides(productId);
        this.recalculateCostPanel(productId);
    }

    async updateManualAvgCost(productId, rawValue) {
        const amount = Number(rawValue);
        if (Number.isNaN(amount) || amount < 0) return;
        this.state.manualAvgCosts = Object.assign({}, this.state.manualAvgCosts, { [productId]: amount });
        this.state.cellPanel = this.state.cellPanel && this.state.cellPanel.productId === productId
            ? Object.assign({}, this.state.cellPanel, { avgCost: amount })
            : this.state.cellPanel;
        this.state.lines = this.state.lines.map((line) => {
            if (line.id !== productId) return line;
            const extra = Object.assign({}, line.extra || {});
            extra.avg_cost = amount;
            extra.manual_avg_override = true;
            return Object.assign({}, line, { extra });
        });
        await this.persistManualOverrides(productId);
        const cacheKey = productId + "-avg_cost";
        const panelData = this.state.cellPanelData[cacheKey];
        if (panelData) {
            panelData.computed_avg = amount;
            panelData.total_value = Number((amount * Number(panelData.total_qty || 0)).toFixed(2));
            panelData.total_tax = Number((panelData.total_tax || 0).toFixed(2));
            this.state.cellPanelData = Object.assign({}, this.state.cellPanelData, { [cacheKey]: panelData });
        }
        this.recalculateCostPanel(productId);
    }

    getColTotal(index) {
        return this.state.lines.reduce((s, l) => s + (l.col_qtys[index] || 0), 0);
    }

    getColOutgoingTotal(index) {
        return this.state.lines.reduce((s, l) => s + ((l.col_outgoing_qtys && l.col_outgoing_qtys[index]) || 0), 0);
    }

    async exportExcel() {
        if (!this.state.groupId) return;
        const _fixedKeys = ["avg_cost", "incoming_qty", "reserved_qty"];
        const _allExtraCols = [...new Set([..._fixedKeys, ...this.state.extraCols])];
        const attId = await this.orm.call(
            "hlv.stock.quick", "export_excel",
            [this.state.groupId, this.state.warehouseIds, this.state.showZero, this.state.includeOutgoing, _allExtraCols]
        );
        window.location.href = "/web/content/" + attId + "?download=true";
    }

    onShowZeroChange(ev) {
        this.state.showZero = ev.target.checked;
        this.loadData();
    }

    onIncludeOutgoingChange(ev) {
        this.state.includeOutgoing = ev.target.checked;
        this.loadData();
    }

    // ── Chon cot ──

    get colOptions() {
        return [
            { key: "sale_price", label: "Gi\u00e1 b\u00e1n (ch\u01b0a VAT)" },
            { key: "price_web", label: "Gi\u00e1 Web" },
            { key: "price_listed", label: "Gi\u00e1 Ni\u00eam Y\u1ebft" },
            { key: "price_tmdt", label: "Gi\u00e1 S\u00e0n TM\u0110T" },
            { key: "price_commercial", label: "Gi\u00e1 Th\u01b0\u01a1ng M\u1ea1i" },
            { key: "purchase_price", label: "Gi\u00e1 mua" },
            { key: "sales_cycle", label: "Chu k\u1ef3 b\u00e1n (ng\u00e0y/\u0111\u01a1n)" },
        ];
    }

    get fixedColDefs() {
        return [
            {
                key: "avg_cost",
                label: "Gi\u00e1 v\u1ed1n TB",
                color: "#880e4f",
                bg: "#fce4ec",
                info: markup("<b>Gi\u00e1 v\u1ed1n trung b\u00ecnh</b><br/>= T\u1ed5ng gi\u00e1 tr\u1ecb h\u00e0ng t\u1ed3n &divide; S\u1ed1 l\u01b0\u1ee3ng t\u1ed3n kho<br/><br/>Odoo t\u1ef1 \u0111\u1ed9ng c\u1eadp nh\u1eadt m\u1ed7i l\u1ea7n nh\u1eadp h\u00e0ng theo ph\u01b0\u01a1ng ph\u00e1p <b>AVCO</b> (average cost). D\u00f9ng \u0111\u1ec3 x\u00e1c \u0111\u1ecbnh bi\u00ean l\u1ee3i nhu\u1eadn th\u1ef1c t\u1ebf."),
            },
            {
                key: "incoming_qty",
                label: "D\u1ef1 ki\u1ebfn nh\u1eadp",
                color: "#1565c0",
                bg: "#e3f2fd",
                info: markup("<b>H\u00e0ng s\u1eafp v\u1ec1</b> \u2014 T\u1ed5ng s\u1ed1 l\u01b0\u1ee3ng t\u1eeb c\u00e1c phi\u1ebfu nh\u1eadp kho \u0111\u00e3 x\u00e1c nh\u1eadn nh\u01b0ng ch\u01b0a ho\u00e0n th\u00e0nh.<br/><br/>Tr\u1ea1ng th\u00e1i: <b>Waiting / Confirmed / Ready</b><br/>Ngu\u1ed3n: \u0111\u01a1n mua, s\u1ea3n xu\u1ea5t, chuy\u1ec3n kho.<br/><br/>Ch\u01b0a ph\u1ea3n \u00e1nh v\u00e0o t\u1ed3n kho hi\u1ec7n t\u1ea1i."),
            },
            {
                key: "reserved_qty",
                label: "D\u1ef1 ki\u1ebfn giao",
                color: "#e65100",
                bg: "#fff3e0",
                info: markup("<b>H\u00e0ng \u0111\u00e3 gi\u1eef cho \u0111\u01a1n</b> \u2014 T\u1ed5ng s\u1ed1 l\u01b0\u1ee3ng t\u1eeb c\u00e1c phi\u1ebfu xu\u1ea5t kho \u0111\u00e3 x\u00e1c nh\u1eadn nh\u01b0ng ch\u01b0a ho\u00e0n th\u00e0nh.<br/><br/>Tr\u1ea1ng th\u00e1i: <b>Waiting / Confirmed / Ready</b><br/>Bao g\u1ed3m: \u0111\u01a1n b\u00e1n, xu\u1ea5t kho, chuy\u1ec3n \u0111i.<br/><br/>T\u1ed3n kho kh\u1ea3 d\u1ee5ng = T\u1ed3n hi\u1ec7n t\u1ea1i \u2212 D\u1ef1 ki\u1ebfn giao."),
            },
        ];
    }

    toggleColsDropdown() {
        this.state.colsOpen = !this.state.colsOpen;
    }

    toggleExtraCol(key) {
        if (this.state.extraCols.includes(key)) {
            this.state.extraCols = this.state.extraCols.filter(k => k !== key);
        } else {
            this.state.extraCols = [...this.state.extraCols, key];
        }
        this.loadData();
    }

    formatExtraVal(key, val) {
        if (val === null || val === undefined) return "-";
        if (key === "sales_cycle") {
            return val.toLocaleString("vi-VN", { maximumFractionDigits: 1 }) + " ng\u00e0y/\u0111\u01a1n";
        }
        if (key === "incoming_qty" || key === "reserved_qty") {
            if (!val || val === 0) return "-";
            return val.toLocaleString("vi-VN", { maximumFractionDigits: 2 });
        }
        // All price keys
        if (key === "avg_cost") {
            return val.toLocaleString("vi-VN", { maximumFractionDigits: 2 }) + " \u20ab";
        }
        return val.toLocaleString("vi-VN", { maximumFractionDigits: 0 }) + " \u20ab";
    }

    formatQty(qty) {
        return qty.toLocaleString("vi-VN", { maximumFractionDigits: 2 });
    }

    get tableColspan() {
        const base = this.state.columns.length > 0 ? this.state.columns.length + 5 : 5;
        return base + this.state.extraCols.length + 3; // +3 for fixed cols
    }

    async toggleProductLocations(productId) {
        if (this.state.expandedProductId === productId) {
            this.state.expandedProductId = false;
            return;
        }
        this.state.expandedProductId = productId;
        if (!this.state.locationData[productId]) {
            const result = await this.orm.call(
                "hlv.stock.quick", "get_product_locations",
                [productId, this.state.warehouseIds]
            );
            this.state.locationData = Object.assign({}, this.state.locationData, { [productId]: result });
        }
    }

    async toggleProductMoves(productId) {
        if (this.state.expandedMovesId === productId) {
            this.state.expandedMovesId = false;
            return;
        }
        this.state.expandedMovesId = productId;
        await this._loadMoves(productId);
    }

    async _loadMoves(productId) {
        // Set null = loading state
        this.state.movesData = Object.assign({}, this.state.movesData, { [productId]: null });
        const result = await this.orm.call(
            "hlv.stock.quick", "get_product_moves",
            [productId, this.state.warehouseIds, this.state.movesDateFrom, this.state.movesDateTo]
        );
        this.state.movesData = Object.assign({}, this.state.movesData, { [productId]: result });
    }

    async exportMoves(productId) {
        const attId = await this.orm.call(
            "hlv.stock.quick", "export_moves_excel",
            [productId, this.state.warehouseIds, this.state.movesDateFrom, this.state.movesDateTo]
        );
        window.location.href = "/web/content/" + attId + "?download=true";
    }

    async exportAllMoves() {
        if (!this.state.groupId || this.state.movesExporting) return;
        this.state.movesExporting = true;
        try {
            const attId = await this.orm.call(
                "hlv.stock.quick", "export_all_moves_excel",
                [this.state.groupId, this.state.warehouseIds, this.state.movesDateFrom, this.state.movesDateTo]
            );
            window.location.href = "/web/content/" + attId + "?download=true";
        } finally {
            this.state.movesExporting = false;
        }
    }

    async reloadMoves(ev, productId) {
        ev.stopPropagation();
        await this._loadMoves(productId);
    }

    onMovesDateFromChange(ev) {
        this.state.movesDateFrom = ev.target.value;
    }

    onMovesDateToChange(ev) {
        this.state.movesDateTo = ev.target.value;
    }

    formatPrice(val) {
        if (!val || val === 0) return "-";
        return val.toLocaleString("vi-VN", { maximumFractionDigits: 2 }) + " \u20ab";
    }

    async handleImportFile(ev) {
        const file = ev.target.files[0];
        if (!file || !this.state.groupId) return;
        this.state.importLoading = true;
        this.state.importResults = null;
        try {
            const buffer = await file.arrayBuffer();
            const bytes = new Uint8Array(buffer);
            let binary = "";
            for (let i = 0; i < bytes.length; i++) { binary += String.fromCharCode(bytes[i]); }
            const b64 = btoa(binary);
            const result = await this.orm.call(
                "hlv.stock.quick", "import_products_from_excel",
                [this.state.groupId, b64]
            );
            this.state.importResults = result;
            await this.loadGroupProducts();
            this.loadData();
        } finally {
            this.state.importLoading = false;
        }
    }

    resetImportFile() {
        this.state.importResults = null;
        const inp = document.getElementById("hlv-import-file");
        if (inp) inp.value = "";
    }
}

registry.category("actions").add("hlv_stock_quick_action", StockQuickView);