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
            warehouseId: false,
            showZero: false,
            lines: [],
            total: 0,
            loading: false,
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
            this.state.total = 0;
            return;
        }
        this.state.loading = true;
        try {
            const result = await this.orm.call(
                "hlv.stock.quick",
                "get_data",
                [this.state.groupId, this.state.warehouseId || false, this.state.showZero]
            );
            this.state.lines = result.lines;
            this.state.total = result.total;
        } finally {
            this.state.loading = false;
        }
    }

    onGroupChange(ev) {
        this.state.groupId = parseInt(ev.target.value) || false;
        this.loadData();
    }

    onWarehouseChange(ev) {
        this.state.warehouseId = parseInt(ev.target.value) || false;
        this.loadData();
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
