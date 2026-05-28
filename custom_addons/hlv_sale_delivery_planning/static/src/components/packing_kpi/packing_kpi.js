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
            searchText: "",
            loading: true,
            summary: {},
            groups: [],
            packers: [],
            expandedGroups: {},
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
                search_text: this.state.searchText || false,
            });
            this.state.summary = result.summary || {};
            this.state.groups = result.groups || [];
            this.state.packers = result.packers || [];
        } finally {
            this.state.loading = false;
        }
    }

    onDateFromChange(ev) { this.state.dateFrom = ev.target.value; }
    onDateToChange(ev) { this.state.dateTo = ev.target.value; }
    onPackerUserIdChange(ev) { this.state.packerUserId = ev.target.value; }

    setRange(mode) {        const now = new Date();
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

    toggleGroup(packerId) {
        // Default is expanded; toggle to collapsed (false) and back
        this.state.expandedGroups[packerId] = this.state.expandedGroups[packerId] === false ? true : false;
    }

    isGroupExpanded(packerId) {
        return this.state.expandedGroups[packerId] !== false;
    }

    groupDonePct(group) {
        return group.assigned_count ? Math.round((group.done_count / group.assigned_count) * 100) : 0;
    }

    async reassignPackerForPick(pickId, newPackerUserId) {
        const uid = parseInt(newPackerUserId, 10);
        if (!uid) return;
        try {
            await this.orm.call("stock.picking", "action_assign_packer", [[pickId]], { packer_user_id: uid });
            await this.fetchData();
        } catch (e) {
            console.error("Reassign packer failed:", e);
        }
    }

    onReassignPackerChange(ev) {
        const pickId = parseInt(ev.target.dataset.pickId, 10);
        this.reassignPackerForPick(pickId, ev.target.value);
    }

    /**
     * Convert UTC datetime string from Odoo to VN time (UTC+7).
     * Input: "2026-04-22 07:30:00" (UTC), Output: "22/04 14:30"
     */
    formatTime(dateStr) {
        if (!dateStr) return '-';
        const utc = new Date(dateStr.replace(' ', 'T') + 'Z');
        if (isNaN(utc.getTime())) return '-';
        const vn = new Date(utc.getTime() + 7 * 3600 * 1000);
        const pad = n => String(n).padStart(2, '0');
        return `${pad(vn.getUTCDate())}/${pad(vn.getUTCMonth() + 1)} ${pad(vn.getUTCHours())}:${pad(vn.getUTCMinutes())}`;
    }
}

registry.category("actions").add("hlv_sale_delivery_planning.packing_kpi", PackingKpiDashboard);
