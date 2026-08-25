/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class StockTraceDashboard extends Component {
    static template = "hlv_stock_trace.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        const context = (this.props.action && this.props.action.context) || {};
        this.productId = context.product_id || context.default_product_id || false;
        this.productName = context.product_name || "";

        const dateFrom = new Date();
        dateFrom.setMonth(dateFrom.getMonth() - 3);

        this.state = useState({
            loading: true,
            error: null,
            view: "company", // company | warehouse | location
            dateFromInput: this._toIso(dateFrom),
            activeRangeMonths: 3,
            warehouseId: null,
            locationId: null,
            locationOrigin: "company", // company | warehouse — where "← quay lại" should go
            data: null,
        });

        onWillStart(() => this.loadCompany());
    }

    // ---------------------------------------------------------- helpers
    _toIso(d) {
        return d.toISOString().slice(0, 10);
    }

    formatVN(dateIso) {
        if (!dateIso || dateIso.indexOf("-") === -1) {
            return dateIso || "";
        }
        const [y, m, d] = dateIso.split("-");
        return `${d}/${m}/${y}`;
    }

    formatQty(value) {
        if (value === null || value === undefined) {
            return "";
        }
        const n = Math.round(value * 100) / 100;
        return n % 1 === 0 ? String(n) : n.toFixed(2);
    }

    signClass(value) {
        if (value > 0) return "o_hst_pos";
        if (value < 0) return "o_hst_neg";
        return "";
    }

    // ---------------------------------------------------------- loaders
    async _call(method, extra) {
        this.state.loading = true;
        this.state.error = null;
        try {
            const args = [this.productId, this.state.dateFromInput, ...(extra || [])];
            return await this.orm.call("stock.trace", method, args);
        } catch (e) {
            this.state.error = (e && e.message && e.message.data && e.message.data.message)
                || (e && e.message)
                || "Không tải được dữ liệu trace.";
            return null;
        } finally {
            this.state.loading = false;
        }
    }

    async loadCompany() {
        const data = await this._call("get_company_overview");
        if (data) {
            this.state.data = data;
            this.state.view = "company";
            this.state.warehouseId = null;
            this.state.locationId = null;
        }
    }

    async loadWarehouse(warehouseId) {
        const data = await this._call("get_warehouse_detail", [warehouseId]);
        if (data) {
            this.state.data = data;
            this.state.view = "warehouse";
            this.state.warehouseId = warehouseId;
            this.state.locationId = null;
        }
    }

    async loadLocation(locationId) {
        const data = await this._call("get_location_timeline", [locationId]);
        if (data) {
            this.state.data = data;
            this.state.view = "location";
            this.state.locationId = locationId;
        }
    }

    // ---------------------------------------------------------- ui events
    onDateInput(ev) {
        this.state.dateFromInput = ev.target.value;
        this.state.activeRangeMonths = null;
    }

    setQuickRange(months) {
        const d = new Date();
        d.setMonth(d.getMonth() - months);
        this.state.dateFromInput = this._toIso(d);
        this.state.activeRangeMonths = months;
        this.reload();
    }

    reload() {
        if (this.state.view === "warehouse" && this.state.warehouseId) {
            return this.loadWarehouse(this.state.warehouseId);
        }
        if (this.state.view === "location" && this.state.locationId) {
            return this.loadLocation(this.state.locationId);
        }
        return this.loadCompany();
    }

    onWarehouseRowClick(warehouseId) {
        if (warehouseId) {
            this.loadWarehouse(warehouseId);
        }
    }

    onLocationRowClick(locationId, origin) {
        this.state.locationOrigin = origin || "company";
        this.loadLocation(locationId);
    }

    backToCompany() {
        this.loadCompany();
    }

    backFromLocation() {
        if (this.state.locationOrigin === "warehouse" && this.state.warehouseId) {
            this.loadWarehouse(this.state.warehouseId);
        } else {
            this.loadCompany();
        }
    }
}

registry.category("actions").add("hlv_stock_trace.dashboard", StockTraceDashboard);
