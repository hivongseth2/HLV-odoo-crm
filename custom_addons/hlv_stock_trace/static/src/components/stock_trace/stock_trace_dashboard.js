/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const CHART_W = 820;
const CHART_H = 130;
const CHART_PAD = 10;

const CATEGORY_LABEL = {
    mua: "Mua vào",
    ban: "Bán hàng",
    chuyen_vao: "Chuyển kho đến",
    chuyen_ra: "Chuyển kho đi",
    chuyen_kho: "Chuyển kho",
    dieu_chinh: "Điều chỉnh kiểm kho",
    opening: "Tồn đầu kỳ",
    current: "Hiện tại",
};

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

            dateFromInput: this._toIso(dateFrom),
            activeRangeMonths: 3,

            scopeType: "company", // company | warehouse | location
            scopeId: null,
            scopeLabel: "Toàn công ty",
            pickerOpen: null, // 'warehouse' | 'location' | null
            scopeOptions: { warehouses: [], locations: [] },

            activeTab: "daily", // daily | structure | timeline
            dailyData: null,
            structureData: null,
            timelineData: null,

            expandedDay: null,
            dayDetail: null,
            dayDetailLoading: false,
            dayDetailTab: "transactions", // transactions | snapshot
        });

        onWillStart(async () => {
            await this._loadScopeOptions();
            await this.loadDaily();
        });
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

    formatSigned(value) {
        if (!value) return "—";
        const s = this.formatQty(Math.abs(value));
        return (value > 0 ? "+" : "−") + s;
    }

    categoryLabel(cat) {
        return CATEGORY_LABEL[cat] || cat;
    }

    /** Positive day count between a LATER date (a) and an EARLIER date (b). */
    daysBetween(a, b) {
        const da = new Date(a + "T00:00:00");
        const db = new Date(b + "T00:00:00");
        return Math.round((da - db) / 86400000);
    }

    // ---------------------------------------------------------- RPC
    async _call(method, args) {
        try {
            return await this.orm.call("stock.trace", method, args);
        } catch (e) {
            this.state.error = (e && e.message && e.message.data && e.message.data.message)
                || (e && e.message)
                || "Không tải được dữ liệu trace.";
            return null;
        }
    }

    async _loadScopeOptions() {
        const data = await this._call("get_scope_options", [this.productId]);
        if (data) {
            this.state.scopeOptions = data;
        }
    }

    async loadDaily() {
        this.state.loading = true;
        this.state.error = null;
        this.state.expandedDay = null;
        this.state.dayDetail = null;
        const data = await this._call("get_daily_ledger", [
            this.productId, this.state.dateFromInput, this.state.scopeType, this.state.scopeId,
        ]);
        this.state.dailyData = data;
        this.state.loading = false;
    }

    async loadStructure() {
        this.state.loading = true;
        this.state.error = null;
        let data;
        if (this.state.scopeType === "warehouse") {
            data = await this._call("get_warehouse_detail", [
                this.productId, this.state.dateFromInput, this.state.scopeId,
            ]);
        } else if (this.state.scopeType === "location") {
            data = await this._call("get_location_timeline", [
                this.productId, this.state.dateFromInput, this.state.scopeId,
            ]);
        } else {
            data = await this._call("get_company_overview", [this.productId, this.state.dateFromInput]);
        }
        this.state.structureData = data;
        this.state.loading = false;
    }

    async loadTimeline() {
        this.state.loading = true;
        this.state.error = null;
        const data = await this._call("get_full_timeline", [
            this.productId, this.state.dateFromInput, this.state.scopeType, this.state.scopeId,
        ]);
        this.state.timelineData = data;
        this.state.loading = false;
    }

    async loadDayDetail(dateStr) {
        this.state.dayDetailLoading = true;
        const data = await this._call("get_day_detail", [
            this.productId, dateStr, this.state.scopeType, this.state.scopeId,
        ]);
        this.state.dayDetail = data;
        this.state.dayDetailLoading = false;
    }

    // ---------------------------------------------------------- scope / tabs
    setScope(type, id, label) {
        this.state.scopeType = type;
        this.state.scopeId = id || null;
        this.state.scopeLabel = label;
        this.state.pickerOpen = null;
        this.state.dailyData = null;
        this.state.structureData = null;
        this.state.timelineData = null;
        this._loadActiveTab();
    }

    togglePicker(which) {
        this.state.pickerOpen = this.state.pickerOpen === which ? null : which;
    }

    setTab(tab) {
        this.state.activeTab = tab;
        if (tab === "daily" && !this.state.dailyData) {
            this.loadDaily();
        } else if (tab === "structure" && !this.state.structureData) {
            this.loadStructure();
        } else if (tab === "timeline" && !this.state.timelineData) {
            this.loadTimeline();
        }
    }

    _loadActiveTab() {
        if (this.state.activeTab === "structure") {
            return this.loadStructure();
        }
        if (this.state.activeTab === "timeline") {
            return this.loadTimeline();
        }
        return this.loadDaily();
    }

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
        this.state.dailyData = null;
        this.state.structureData = null;
        this.state.timelineData = null;
        return this._loadActiveTab();
    }

    toggleDayExpand(dateStr) {
        if (this.state.expandedDay === dateStr) {
            this.state.expandedDay = null;
            this.state.dayDetail = null;
            return;
        }
        this.state.expandedDay = dateStr;
        this.state.dayDetailTab = "transactions";
        this.loadDayDetail(dateStr);
    }

    setDayDetailTab(tab) {
        this.state.dayDetailTab = tab;
    }

    onStructureWarehouseClick(warehouseId, name) {
        if (warehouseId) {
            this.setScope("warehouse", warehouseId, name);
        }
    }

    onStructureLocationClick(locationId, name) {
        this.setScope("location", locationId, name);
    }

    // ---------------------------------------------------------- chart geometry
    get chartGeometry() {
        const data = this.state.dailyData;
        if (!data) return null;
        const start = new Date(data.date_from + "T00:00:00");
        const end = new Date(data.date_to + "T00:00:00");
        const totalMs = Math.max(1, end - start);
        const toX = (dstr) => {
            const dt = new Date(dstr + "T00:00:00");
            return Math.max(0, Math.min(CHART_W, ((dt - start) / totalMs) * CHART_W));
        };

        const days = [...data.days].reverse(); // ascending chronological
        const balances = [data.opening, data.closing, ...days.map((d) => d.balance)];
        const minB = Math.min(0, ...balances);
        const maxB = Math.max(1, ...balances);
        const span = Math.max(1, maxB - minB);
        const innerH = CHART_H - CHART_PAD * 2;
        const toY = (v) => CHART_PAD + (1 - (v - minB) / span) * innerH;

        let pathD = `M0,${toY(data.opening).toFixed(1)}`;
        let prev = data.opening;
        const dots = [];
        for (const day of days) {
            const x = toX(day.date);
            pathD += ` L${x.toFixed(1)},${toY(prev).toFixed(1)} L${x.toFixed(1)},${toY(day.balance).toFixed(1)}`;
            dots.push({
                x: x.toFixed(1), y: toY(day.balance).toFixed(1),
                cls: day.net > 0 ? "o_hst_dot_up" : (day.net < 0 ? "o_hst_dot_down" : "o_hst_dot_flat"),
            });
            prev = day.balance;
        }
        pathD += ` L${CHART_W},${toY(prev).toFixed(1)}`;
        const areaD = `${pathD} L${CHART_W},${CHART_H} L0,${CHART_H} Z`;

        return {
            pathD, areaD, dots,
            width: CHART_W, height: CHART_H,
            startY: toY(data.opening).toFixed(1),
            endY: toY(prev).toFixed(1),
            gridLines: [0, 0.33, 0.66, 1].map((f) => (CHART_PAD + f * innerH).toFixed(1)),
        };
    }

    // ---------------------------------------------------------- ledger rows + collapsed gaps
    get ledgerEntries() {
        const data = this.state.dailyData;
        if (!data) return [];
        const days = data.days; // descending (most recent first)
        const entries = [];
        for (let i = 0; i < days.length; i++) {
            entries.push({ type: "day", ...days[i] });
            const nextDateStr = i + 1 < days.length ? days[i + 1].date : data.date_from;
            const gapDays = this.daysBetween(days[i].date, nextDateStr) - 1;
            if (gapDays > 0) {
                const gapEnd = new Date(days[i].date + "T00:00:00");
                gapEnd.setDate(gapEnd.getDate() - 1);
                const gapStart = new Date(nextDateStr + "T00:00:00");
                gapStart.setDate(gapStart.getDate() + 1);
                entries.push({
                    type: "gap", count: gapDays,
                    from: this._toIso(gapStart), to: this._toIso(gapEnd),
                });
            }
        }
        entries.push({ type: "opening", date: data.date_from, balance: data.opening });
        return entries;
    }
}

registry.category("actions").add("hlv_stock_trace.dashboard", StockTraceDashboard);
