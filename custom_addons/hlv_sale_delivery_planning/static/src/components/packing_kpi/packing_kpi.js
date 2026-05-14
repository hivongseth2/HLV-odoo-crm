/** @odoo-module **/
import { Component, useState, onWillStart, onWillDestroy } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class PackingKpiDashboard extends Component {
    static template = "hlv_sale_delivery_planning.PackingKpiDashboard";

    setup() {
        this.notification = useService("notification");
        try {
            this.busService = useService("bus_service");
        } catch (e) {
            this.busService = null;
        }

        // Default date range: current month
        const now = new Date();
        const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
        const pad = (n) => String(n).padStart(2, "0");
        const fmtDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

        this.state = useState({
            loading: false,
            // Filters
            dateFrom: fmtDate(firstDay),
            dateTo: fmtDate(now),
            selectedPackerIds: [],   // int[]
            selectedStatuses: [],    // string[]
            page: 1,
            pageSize: 50,
            // Data
            summary: null,
            packerKpi: [],
            rows: [],
            pagination: null,
            allPackers: [],          // [{id, name}] for dropdown
            // UI
            packerDropdownOpen: false,
            statusDropdownOpen: false,
        });

        onWillStart(() => this.fetchData());

        // Bus: auto-refresh when packing data changes (same channel as dashboard)
        if (this.busService) {
            this.busService.addChannel("delivery_planner_channel");
            this._onBusPackingChanged = () => {
                if (this._packingRefreshDebounce) clearTimeout(this._packingRefreshDebounce);
                this._packingRefreshDebounce = setTimeout(() => {
                    this._packingRefreshDebounce = null;
                    this.fetchData();
                }, 1000);
            };
            this.busService.subscribe("delivery_planner_data_changed", this._onBusPackingChanged);
        }

        onWillDestroy(() => {
            if (this.busService) {
                if (this._onBusPackingChanged) {
                    this.busService.unsubscribe("delivery_planner_data_changed", this._onBusPackingChanged);
                }
                this.busService.deleteChannel("delivery_planner_channel");
            }
            if (this._packingRefreshDebounce) clearTimeout(this._packingRefreshDebounce);
        });
    }

    // ── Filters ────────────────────────────────────────────────────────────────

    onDateFromChange(ev) {
        this.state.dateFrom = ev.target.value;
    }
    onDateToChange(ev) {
        this.state.dateTo = ev.target.value;
    }

    setPreset(preset) {
        const now = new Date();
        const pad = (n) => String(n).padStart(2, "0");
        const fmt = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
        if (preset === "today") {
            this.state.dateFrom = fmt(now);
            this.state.dateTo = fmt(now);
        } else if (preset === "week") {
            const mon = new Date(now);
            mon.setDate(now.getDate() - ((now.getDay() + 6) % 7));
            this.state.dateFrom = fmt(mon);
            this.state.dateTo = fmt(now);
        } else if (preset === "month") {
            this.state.dateFrom = fmt(new Date(now.getFullYear(), now.getMonth(), 1));
            this.state.dateTo = fmt(now);
        }
        this.state.page = 1;
        this.fetchData();
    }

    togglePacker(id) {
        const idx = this.state.selectedPackerIds.indexOf(id);
        if (idx === -1) this.state.selectedPackerIds.push(id);
        else this.state.selectedPackerIds.splice(idx, 1);
    }
    isPackerSelected(id) {
        return this.state.selectedPackerIds.includes(id);
    }

    toggleStatus(s) {
        const idx = this.state.selectedStatuses.indexOf(s);
        if (idx === -1) this.state.selectedStatuses.push(s);
        else this.state.selectedStatuses.splice(idx, 1);
    }
    isStatusSelected(s) {
        return this.state.selectedStatuses.includes(s);
    }

    clearFilters() {
        this.state.selectedPackerIds = [];
        this.state.selectedStatuses = [];
        this.state.page = 1;
        this.fetchData();
    }

    applyFilters() {
        this.state.page = 1;
        this.state.packerDropdownOpen = false;
        this.state.statusDropdownOpen = false;
        this.fetchData();
    }

    // ── Pagination ──────────────────────────────────────────────────────────────

    goPage(p) {
        if (!this.state.pagination) return;
        if (p < 1 || p > this.state.pagination.pages) return;
        this.state.page = p;
        this.fetchData();
    }

    get pageRange() {
        if (!this.state.pagination) return [];
        const pages = this.state.pagination.pages;
        const cur = this.state.page;
        const range = [];
        for (let i = Math.max(1, cur - 2); i <= Math.min(pages, cur + 2); i++) {
            range.push(i);
        }
        return range;
    }

    // ── Data fetch ──────────────────────────────────────────────────────────────

    async fetchData() {
        if (this.state.loading) return;
        this.state.loading = true;
        try {
            const res = await fetch(
                "/hlv_sale_delivery_planning/packing_kpi_history",
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        jsonrpc: "2.0",
                        method: "call",
                        params: {
                            date_from: this.state.dateFrom,
                            date_to: this.state.dateTo,
                            packer_ids: this.state.selectedPackerIds,
                            status: this.state.selectedStatuses,
                            page: this.state.page,
                            page_size: this.state.pageSize,
                        },
                    }),
                }
            ).then((r) => r.json());

            const data = res.result || {};
            if (data.success === false) {
                this.notification.add("Lỗi: " + (data.message || "unknown"), { type: "danger" });
                return;
            }
            this.state.summary = data.summary || null;
            this.state.packerKpi = data.packer_kpi || [];
            this.state.rows = data.rows || [];
            this.state.pagination = data.pagination || null;
            if (data.all_packers && data.all_packers.length) {
                this.state.allPackers = data.all_packers;
            }
        } catch (e) {
            console.error("packing_kpi_history error", e);
            this.notification.add("Không thể tải dữ liệu KPI", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    // ── Helpers ──────────────────────────────────────────────────────────────────

    statusLabel(s) {
        const map = { pending: "Đang chờ", packing: "Đang đóng", packed: "Đã xong" };
        return map[s] || s;
    }

    statusBadgeClass(s) {
        const map = {
            pending: "bg-secondary",
            packing: "bg-warning text-dark",
            packed: "bg-success",
        };
        return "badge " + (map[s] || "bg-light text-dark");
    }

    stateLabel(s) {
        const map = {
            draft: "Nháp", confirmed: "Đã xác nhận",
            assigned: "Sẵn sàng", done: "Hoàn thành", cancel: "Đã hủy",
        };
        return map[s] || s;
    }

    get hasActiveFilters() {
        return this.state.selectedPackerIds.length > 0 || this.state.selectedStatuses.length > 0;
    }

    get selectedPackerNames() {
        return this.state.selectedPackerIds
            .map((id) => {
                const p = this.state.allPackers.find((x) => x.id === id);
                return p ? p.name : id;
            })
            .join(", ");
    }

    get selectedStatusLabels() {
        return this.state.selectedStatuses.map((s) => this.statusLabel(s)).join(", ");
    }
}

registry.category("actions").add("hlv_sale_delivery_planning.packing_kpi", PackingKpiDashboard);
