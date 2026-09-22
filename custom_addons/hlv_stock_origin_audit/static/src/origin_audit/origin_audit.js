/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const SEVERITY_LABEL = {
    ok: "Bình thường",
    info: "Để ý",
    warn: "Nghi ngờ",
    alert: "Báo động",
};

export class OriginAuditDashboard extends Component {
    static template = "hlv_stock_origin_audit.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        const context = (this.props.action && this.props.action.context) || {};
        const product = context.product_id
            ? { id: context.product_id, name: context.product_name || "" }
            : null;

        this.state = useState({
            tab: product ? "investigate" : "scan",
            options: { warehouses: [], rules: [] },
            filters: { warehouseId: false, days: 60, stuckDays: 7, rules: [] },

            scan: null,
            scanLoading: false,

            term: product ? product.name : "",
            suggestions: [],
            product,
            overview: null,
            overviewLoading: false,

            result: null,
            resultLoading: false,
            showLedger: false,

            recent: null,
            recentLoading: false,

            error: null,
        });

        onWillStart(async () => {
            await this._guard(async () => {
                const options = await this.orm.call("stock.origin.scan", "get_scan_options", []);
                this.state.options = options;
                this.state.filters.rules = options.rules
                    .filter((rule) => !rule.heavy)
                    .map((rule) => rule.code);
            });
            if (this.state.product) {
                await this.loadOverview();
            } else {
                await this.runScan();
            }
        });
    }

    // ------------------------------------------------------------ helpers
    async _guard(fn) {
        try {
            this.state.error = null;
            await fn();
        } catch (error) {
            this.state.error = (error && error.message && error.message.data)
                ? error.message.data.message
                : String((error && error.message) || error);
        }
    }

    severityLabel(code) {
        return SEVERITY_LABEL[code] || "";
    }

    hasRule(code) {
        return this.state.filters.rules.includes(code);
    }

    ruleCount(code) {
        const counts = (this.state.scan && this.state.scan.counts) || {};
        return counts[code] === undefined ? "" : counts[code];
    }

    // ------------------------------------------------------------- quét
    setTab(tab) {
        this.state.tab = tab;
    }

    toggleRule(code) {
        const rules = this.state.filters.rules;
        const index = rules.indexOf(code);
        if (index === -1) {
            rules.push(code);
        } else {
            rules.splice(index, 1);
        }
    }

    onWarehouseChange(ev) {
        this.state.filters.warehouseId = parseInt(ev.target.value, 10) || false;
    }

    onDaysChange(ev) {
        this.state.filters.days = parseInt(ev.target.value, 10) || 60;
    }

    onStuckDaysChange(ev) {
        this.state.filters.stuckDays = parseInt(ev.target.value, 10) || 0;
    }

    async runScan() {
        this.state.scanLoading = true;
        await this._guard(async () => {
            this.state.scan = await this.orm.call("stock.origin.scan", "scan", [], {
                warehouse_id: this.state.filters.warehouseId,
                days: this.state.filters.days,
                stuck_days: this.state.filters.stuckDays,
                rules: this.state.filters.rules,
            });
        });
        this.state.scanLoading = false;
    }

    // -------------------------------------------------------- chọn sản phẩm
    async onTermInput(ev) {
        const term = ev.target.value;
        this.state.term = term;
        if (term.trim().length < 2) {
            this.state.suggestions = [];
            return;
        }
        await this._guard(async () => {
            this.state.suggestions = await this.orm.call(
                "stock.origin.audit", "search_products", [term],
            );
        });
    }

    async pickProduct(product) {
        this.state.product = product;
        this.state.term = product.name;
        this.state.suggestions = [];
        this.state.result = null;
        this.state.recent = null;
        await this.loadOverview();
    }

    async loadOverview() {
        if (!this.state.product) {
            return;
        }
        this.state.overviewLoading = true;
        await this._guard(async () => {
            this.state.overview = await this.orm.call(
                "stock.origin.audit", "get_product_overview", [this.state.product.id],
            );
        });
        this.state.overviewLoading = false;
    }

    // ------------------------------------------------------------ điều tra
    async investigate(productId, locationId, lotId) {
        this.state.tab = "investigate";
        this.state.resultLoading = true;
        this.state.showLedger = false;
        await this._guard(async () => {
            this.state.result = await this.orm.call(
                "stock.origin.audit", "investigate", [productId, locationId, lotId || false],
                { stuck_days: this.state.filters.stuckDays },
            );
            this.state.product = this.state.result.product;
            this.state.term = this.state.result.product.name;
        });
        this.state.resultLoading = false;
        if (this.state.result && !this.state.overview) {
            await this.loadOverview();
        }
    }

    async investigateRow(row) {
        await this.investigate(row.product_id, row.location_id, row.lot_id);
    }

    async investigateOverviewRow(row) {
        await this.investigate(this.state.product.id, row.location_id, row.lot_id);
    }

    closeResult() {
        this.state.result = null;
    }

    toggleLedger() {
        this.state.showLedger = !this.state.showLedger;
    }

    async loadRecent() {
        if (!this.state.product) {
            return;
        }
        this.state.recentLoading = true;
        await this._guard(async () => {
            this.state.recent = await this.orm.call(
                "stock.origin.audit", "recent_incoming_moves", [this.state.product.id],
                { days: 90 },
            );
        });
        this.state.recentLoading = false;
    }

    // -------------------------------------------------------- mở bản ghi gốc
    openPicking(pickingId) {
        if (!pickingId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            res_id: pickingId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openMoveLines(productId, locationId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Chi tiết di chuyển",
            res_model: "stock.move.line",
            views: [[false, "list"], [false, "form"]],
            domain: [
                ["product_id", "=", productId],
                ["state", "=", "done"],
                "|",
                ["location_id", "=", locationId],
                ["location_dest_id", "=", locationId],
            ],
            target: "current",
        });
    }
}

registry.category("actions").add("hlv_stock_origin_audit.dashboard", OriginAuditDashboard);
