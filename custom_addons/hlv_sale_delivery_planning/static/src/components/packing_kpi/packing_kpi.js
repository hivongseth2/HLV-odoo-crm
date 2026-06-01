/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onWillUnmount, useState, useRef, useEffect } from "@odoo/owl";
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
            packingState: "all",
            searchText: "",
            loading: true,
            summary: {},
            groups: [],
            packers: [],
            expandedGroups: {},
            showCharts: true,
            dailyChartData: null,
            _chartVersion: 0,
        });

        this.chartDailyRef = useRef("chartDaily");
        this.chartPackerRef = useRef("chartPacker");
        this.chartDurationRef = useRef("chartDuration");
        this._charts = {};

        useEffect(
            () => { this._renderCharts(); },
            () => [this.state._chartVersion, this.state.showCharts, this.state.loading]
        );

        onWillUnmount(() => this._destroyCharts());
        onWillStart(() => this.fetchData());
    }

    async fetchData() {
        this.state.loading = true;
        try {
            const params = {
                date_from: this.state.dateFrom,
                date_to: this.state.dateTo,
                packer_user_id: this.state.packerUserId,
                packing_state: this.state.packingState,
            };
            const [result, daily] = await Promise.all([
                this.orm.call("stock.picking", "get_packing_kpi_dashboard", [], {
                    ...params,
                    search_text: this.state.searchText || false,
                }),
                this.orm.call("stock.picking", "get_packing_kpi_daily_chart", [], params),
            ]);
            this.state.summary = result.summary || {};
            this.state.groups = result.groups || [];
            this.state.packers = result.packers || [];
            this.state.dailyChartData = daily;
            this.state._chartVersion += 1;
        } finally {
            this.state.loading = false;
        }
    }

    _destroyCharts() {
        Object.values(this._charts).forEach(c => { try { c.destroy(); } catch (e) {} });
        this._charts = {};
    }

    _renderCharts() {
        if (!this.state.showCharts) { this._destroyCharts(); return; }
        if (this.state.loading) return;
        const Chart = window.Chart;
        if (!Chart) {
            this._destroyCharts();
            this._renderCanvasFallbackCharts();
            return;
        }

        this._destroyCharts();

        const COLORS = {
            green: 'rgba(76,175,80,0.85)',
            yellow: 'rgba(255,193,7,0.85)',
            grey: 'rgba(158,158,158,0.7)',
            blue: 'rgba(33,150,243,0.85)',
        };
        const baseOpts = {
            responsive: true,
            maintainAspectRatio: true,
            plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } } },
        };

        // Chart 1: Daily trend
        const dailyEl = this.chartDailyRef.el;
        const cd = this.state.dailyChartData;
        if (dailyEl && cd && cd.labels && cd.labels.length) {
            this._charts.daily = new Chart(dailyEl, {
                type: 'bar',
                data: {
                    labels: cd.labels.map(d => d.slice(5)),
                    datasets: [
                        { label: 'Hoàn thành', data: cd.done, backgroundColor: COLORS.green, borderRadius: 4 },
                        { label: 'Đang đóng', data: cd.in_progress, backgroundColor: COLORS.yellow, borderRadius: 4 },
                        { label: 'Mới assign', data: cd.assigned.map((a, i) => Math.max(a - (cd.done[i] || 0) - (cd.in_progress[i] || 0), 0)), backgroundColor: COLORS.grey, borderRadius: 4 },
                    ],
                },
                options: {
                    ...baseOpts,
                    scales: {
                        x: { stacked: true, ticks: { font: { size: 10 } } },
                        y: { stacked: true, beginAtZero: true, ticks: { stepSize: 1, font: { size: 10 } } },
                    },
                },
            });
        }

        const groups = this.state.groups;
        if (!groups.length) return;
        const packerLabels = groups.map(g => g.packer_name);

        // Chart 2: Per-packer productivity stacked bar
        const packerEl = this.chartPackerRef.el;
        if (packerEl) {
            this._charts.packer = new Chart(packerEl, {
                type: 'bar',
                data: {
                    labels: packerLabels,
                    datasets: [
                        { label: 'Hoàn thành', data: groups.map(g => g.done_count), backgroundColor: COLORS.green, borderRadius: 4 },
                        { label: 'Đang đóng', data: groups.map(g => g.in_progress_count), backgroundColor: COLORS.yellow, borderRadius: 4 },
                        { label: 'Chưa bắt đầu', data: groups.map(g => Math.max(g.assigned_count - g.done_count - g.in_progress_count, 0)), backgroundColor: COLORS.grey, borderRadius: 4 },
                    ],
                },
                options: {
                    ...baseOpts,
                    scales: {
                        x: { stacked: true, ticks: { font: { size: 10 } } },
                        y: { stacked: true, beginAtZero: true, ticks: { stepSize: 1, font: { size: 10 } } },
                    },
                },
            });
        }

        // Chart 3: Avg duration per packer
        const durationEl = this.chartDurationRef.el;
        if (durationEl) {
            const data = groups.map(g => Math.round((g.avg_actual_seconds || g.avg_print_to_done_seconds || 0) / 60));
            this._charts.duration = new Chart(durationEl, {
                type: 'bar',
                data: {
                    labels: packerLabels,
                    datasets: [{
                        label: 'TB thời gian (phút)',
                        data,
                        backgroundColor: packerLabels.map((_, i) => `hsla(${200 + i * 35},65%,55%,0.85)`),
                        borderRadius: 4,
                    }],
                },
                options: {
                    ...baseOpts,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { beginAtZero: true, ticks: { font: { size: 10 } }, title: { display: true, text: 'Phút', font: { size: 10 } } },
                        x: { ticks: { font: { size: 10 } } },
                    },
                },
            });
        }
    }

    _renderCanvasFallbackCharts() {
        const colors = {
            green: 'rgba(76,175,80,0.85)',
            yellow: 'rgba(255,193,7,0.85)',
            grey: 'rgba(158,158,158,0.7)',
            blue: 'rgba(33,150,243,0.85)',
        };
        const cd = this.state.dailyChartData || {};
        if (this.chartDailyRef.el && cd.labels && cd.labels.length) {
            this._drawStackedBars(this.chartDailyRef.el, cd.labels.map(d => d.slice(5)), [
                { values: cd.done || [], color: colors.green },
                { values: cd.in_progress || [], color: colors.yellow },
                { values: (cd.assigned || []).map((a, i) => Math.max(a - (cd.done?.[i] || 0) - (cd.in_progress?.[i] || 0), 0)), color: colors.grey },
            ]);
        }
        const groups = this.state.groups || [];
        if (!groups.length) return;
        const labels = groups.map(g => g.packer_name);
        if (this.chartPackerRef.el) {
            this._drawStackedBars(this.chartPackerRef.el, labels, [
                { values: groups.map(g => g.done_count || 0), color: colors.green },
                { values: groups.map(g => g.in_progress_count || 0), color: colors.yellow },
                { values: groups.map(g => Math.max((g.assigned_count || 0) - (g.done_count || 0) - (g.in_progress_count || 0), 0)), color: colors.grey },
            ]);
        }
        if (this.chartDurationRef.el) {
            this._drawBars(
                this.chartDurationRef.el,
                labels,
                groups.map(g => Math.round((g.avg_actual_seconds || g.avg_print_to_done_seconds || 0) / 60)),
                colors.blue
            );
        }
    }

    _prepareCanvas(canvas) {
        const width = Math.max(canvas.parentElement?.clientWidth || 320, 240);
        const height = 200;
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, width, height);
        ctx.font = '11px sans-serif';
        ctx.fillStyle = '#6c757d';
        return { ctx, width, height, pad: { top: 12, right: 10, bottom: 34, left: 28 } };
    }

    _drawStackedBars(canvas, labels, datasets) {
        const { ctx, width, height, pad } = this._prepareCanvas(canvas);
        const totals = labels.map((_, i) => datasets.reduce((sum, ds) => sum + (ds.values[i] || 0), 0));
        const max = Math.max(...totals, 1);
        this._drawBarFrame(ctx, width, height, pad, max);
        this._drawBarSeries(ctx, width, height, pad, labels, datasets, max, true);
    }

    _drawBars(canvas, labels, values, color) {
        const { ctx, width, height, pad } = this._prepareCanvas(canvas);
        const max = Math.max(...values, 1);
        this._drawBarFrame(ctx, width, height, pad, max);
        this._drawBarSeries(ctx, width, height, pad, labels, [{ values, color }], max, false);
    }

    _drawBarFrame(ctx, width, height, pad, max) {
        ctx.strokeStyle = '#dee2e6';
        ctx.beginPath();
        ctx.moveTo(pad.left, pad.top);
        ctx.lineTo(pad.left, height - pad.bottom);
        ctx.lineTo(width - pad.right, height - pad.bottom);
        ctx.stroke();
        ctx.fillStyle = '#6c757d';
        ctx.fillText(String(max), 4, pad.top + 8);
        ctx.fillText('0', 12, height - pad.bottom);
    }

    _drawBarSeries(ctx, width, height, pad, labels, datasets, max, stacked) {
        const plotW = width - pad.left - pad.right;
        const plotH = height - pad.top - pad.bottom;
        const slot = plotW / Math.max(labels.length, 1);
        const barW = Math.min(slot * 0.62, 34);
        labels.forEach((label, i) => {
            const x = pad.left + slot * i + (slot - barW) / 2;
            let yBase = height - pad.bottom;
            datasets.forEach(ds => {
                const value = ds.values[i] || 0;
                const h = Math.round((value / max) * plotH);
                const y = stacked ? yBase - h : height - pad.bottom - h;
                ctx.fillStyle = ds.color;
                ctx.fillRect(x, y, barW, h);
                if (stacked) yBase = y;
            });
            ctx.save();
            ctx.translate(x + barW / 2, height - 8);
            ctx.rotate(-Math.PI / 8);
            ctx.fillStyle = '#6c757d';
            ctx.textAlign = 'center';
            ctx.fillText(String(label || '').slice(0, 10), 0, 0);
            ctx.restore();
        });
    }

    toggleCharts() {
        this.state.showCharts = !this.state.showCharts;
    }

    onDateFromChange(ev) { this.state.dateFrom = ev.target.value; }
    onDateToChange(ev) { this.state.dateTo = ev.target.value; }
    onPackerUserIdChange(ev) { this.state.packerUserId = ev.target.value; }
    onPackingStateChange(ev) { this.state.packingState = ev.target.value; }

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

    toggleGroup(packerId) {
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

    onSearchInput(ev) {
        this.state.searchText = ev.target.value;
    }

    onSearchKeydown(ev) {
        if (ev.key === 'Enter') this.fetchData();
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
