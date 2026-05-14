/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class StockQuickView extends Component {
    static template = "hlv_inventory_group_report.StockQuickView";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
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
            const result = await this.orm.call(
                "hlv.stock.quick", "get_data",
                [this.state.groupId, this.state.warehouseIds, this.state.showZero]
            );
            this.state.lines = result.lines;
            this.state.columns = result.columns;
            this.state.total = result.total;
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

    async searchProducts() {
        const query = this.state.productQuery.trim();
        if (!query) return;
        this.state.productLoading = true;
        try {
            const excludeIds = this.state.groupProducts.map(p => p.id);
            const results = await this.orm.call(
                "hlv.stock.quick", "search_products", [query, excludeIds]
            );
            this.state.productResults = results;
        } finally {
            this.state.productLoading = false;
        }
    }

    async addProductToGroup(productId) {
        await this.orm.write("hlv.product.report.group", [this.state.groupId], {
            product_ids: [[4, productId]],
        });
        await this.loadGroupProducts();
        this.state.productResults = this.state.productResults.filter(p => p.id !== productId);
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
    }

    getColTotal(index) {
        return this.state.lines.reduce((s, l) => s + (l.col_qtys[index] || 0), 0);
    }

    async exportExcel() {
        if (!this.state.groupId) return;
        const attId = await this.orm.call(
            "hlv.stock.quick", "export_excel",
            [this.state.groupId, this.state.warehouseIds, this.state.showZero]
        );
        window.location.href = "/web/content/" + attId + "?download=true";
    }

    onShowZeroChange(ev) {
        this.state.showZero = ev.target.checked;
        this.loadData();
    }

    formatQty(qty) {
        return qty.toLocaleString("vi-VN", { maximumFractionDigits: 2 });
    }
}

registry.category("actions").add("hlv_stock_quick_action", StockQuickView);