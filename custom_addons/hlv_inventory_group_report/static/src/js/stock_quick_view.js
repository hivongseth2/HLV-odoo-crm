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
        });

        onWillStart(async () => {
            const ctx = this.props.action?.context || {};
            if (ctx.default_group_id) {
                this.state.groupId = ctx.default_group_id;
            }
            const [groups, warehouses] = await Promise.all([
                this.orm.searchRead(
                    "hlv.product.report.group",
                    [["active", "=", true]],
                    ["id", "name"],
                    { order: "sequence, name" }
                ),
                this.orm.searchRead(
                    "stock.warehouse",
                    [],
                    ["id", "name"],
                    { order: "name" }
                ),
            ]);
            this.state.groups = groups;
            this.state.warehouses = warehouses;
            if (this.state.groupId) {
                await this.loadData();
            }
        });
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
                "hlv.stock.quick",
                "get_data",
                [this.state.groupId, this.state.warehouseIds, this.state.showZero]
            );
            this.state.lines = result.lines;
            this.state.columns = result.columns;
            this.state.total = result.total;
        } finally {
            this.state.loading = false;
        }
    }

    onGroupChange(ev) {
        this.state.groupId = parseInt(ev.target.value) || false;
        this.loadData();
    }

    get warehouseSummary() {
        const n = this.state.warehouseIds.length;
        if (n === 0) return "Tất cả kho";
        if (n === 1) {
            const wh = this.state.warehouses.find(w => w.id === this.state.warehouseIds[0]);
            return wh ? wh.name : "1 kho";
        }
        return n + " kho đã chọn";
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
            "hlv.stock.quick",
            "export_excel",
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
