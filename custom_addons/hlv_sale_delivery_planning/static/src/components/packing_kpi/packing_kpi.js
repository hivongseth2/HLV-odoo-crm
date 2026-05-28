/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class PackingKpiDashboard extends Component {
    static template = "hlv_sale_delivery_planning.PackingKpiDashboard";

    setup() {
        this.orm = useService("orm");
        const today = new Date().toISOString().slice(0, 10);
        this.state = useState({
            dateFrom: today,
            dateTo: today,
            packerUserId: "all",
            loading: true,
            summary: {},
            groups: [],
            packers: [],
        });
        onWillStart(() => this.fetchData());
    }

    async fetchData() {
        this.state.loading = true;
        try {
            const result = await this.orm.call("stock.picking", "get_packing_kpi_dashboard", [], {
                date_from: this.state.dateFrom,
                date_to: this.state.dateTo,
                packer_user_id: this.state.packerUserId,
            });
            this.state.summary = result.summary || {};
            this.state.groups = result.groups || [];
            this.state.packers = result.packers || [];
        } finally {
            this.state.loading = false;
        }
    }

    setRange(mode) {
        const now = new Date();
        const toDate = new Date(now);
        const fromDate = new Date(now);
        if (mode === "week") {
            const day = fromDate.getDay() || 7;
            fromDate.setDate(fromDate.getDate() - day + 1);
        } else if (mode === "month") {
            fromDate.setDate(1);
        }
        this.state.dateFrom = fromDate.toISOString().slice(0, 10);
        this.state.dateTo = toDate.toISOString().slice(0, 10);
        this.fetchData();
    }

    formatDuration(seconds) {
        seconds = Math.round(seconds || 0);
        if (!seconds) return "-";
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        if (hours) return `${hours}h ${minutes}m`;
        return `${minutes}m`;
    }

    stateLabel(state) {
        return { assigned: "Đã assign", in_progress: "Đang đóng", done: "Hoàn thành" }[state] || state;
    }

    stateClass(state) {
        if (state === "done") return "text-bg-success";
        if (state === "in_progress") return "text-bg-warning";
        return "text-bg-secondary";
    }
}

registry.category("actions").add("hlv_sale_delivery_planning.packing_kpi", PackingKpiDashboard);
