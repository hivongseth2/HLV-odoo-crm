/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onWillUnmount, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class WarehouseMonitorDashboard extends Component {
    static template = "hlv_warehouse_monitor.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.suggestionsPanel = useRef("suggestionsPanel");

        this.state = useState({
            isLoading: true,
            isRefreshing: false,
            warehouseId: "all",
            eventTypeFilter: "all",
            events: [],
            suggestions: [],
            warehouses: [],
            totalCount: 0,
            offset: 0,
            pageSize: 50,
            countdown: 30,
            kpi: {
                total_events_today: 0,
                in_today: 0,
                out_today: 0,
                pick_today: 0,
                pack_today: 0,
                sale_today: 0,
                purchase_today: 0,
                suggestions_pending: 0,
            },
        });

        // Auto-refresh interval
        this._refreshInterval = null;

        onWillStart(async () => {
            await this.fetchData();
            // 1-second ticker: counts down and triggers refresh every 30s
            this._refreshInterval = setInterval(() => {
                this.state.countdown -= 1;
                if (this.state.countdown <= 0) {
                    this.state.countdown = 30;
                    this.silentRefresh();
                }
            }, 1000);
        });

        onWillUnmount(() => {
            if (this._refreshInterval) {
                clearInterval(this._refreshInterval);
                this._refreshInterval = null;
            }
        });
    }

    // ── Data Fetching ───────────────────────────────────────
    async fetchData() {
        try {
            const result = await this.orm.call(
                "warehouse.monitor.event",
                "get_monitor_dashboard_data",
                [],
                {
                    warehouse_id: this.state.warehouseId,
                    event_type: this.state.eventTypeFilter,
                    limit: this.state.pageSize,
                    offset: this.state.offset,
                }
            );

            this.state.events = result.events || [];
            this.state.suggestions = result.suggestions || [];
            this.state.warehouses = result.warehouses || [];
            this.state.totalCount = result.total_count || 0;
            this.state.kpi = result.kpi || this.state.kpi;
            this.state.isLoading = false;
            this.state.isRefreshing = false;
        } catch (error) {
            console.error("[HLV Monitor] Error fetching data:", error);
            this.state.isLoading = false;
            this.state.isRefreshing = false;
            this.notification.add("Lỗi tải dữ liệu giám sát", { type: "danger" });
        }
    }

    async silentRefresh() {
        try {
            const result = await this.orm.call(
                "warehouse.monitor.event",
                "get_monitor_dashboard_data",
                [],
                {
                    warehouse_id: this.state.warehouseId,
                    event_type: this.state.eventTypeFilter,
                    limit: this.state.pageSize,
                    offset: this.state.offset,
                }
            );

            this.state.events = result.events || [];
            this.state.suggestions = result.suggestions || [];
            this.state.totalCount = result.total_count || 0;
            this.state.kpi = result.kpi || this.state.kpi;

            // Notify if new suggestions
            if (result.suggestions && result.suggestions.length > 0) {
                const newCount = result.suggestions.length;
                const kpiCount = this.state.kpi.suggestions_pending;
                if (newCount > kpiCount) {
                    this.notification.add(
                        `${newCount} đề xuất mới cần xử lý`,
                        { type: "warning", sticky: false }
                    );
                }
            }
        } catch {
            // Silent fail on auto-refresh
        }
    }

    // ── Actions ─────────────────────────────────────────────
    async refresh() {
        this.state.isRefreshing = true;
        this.state.countdown = 30;
        this.state.offset = 0;
        await this.fetchData();
    }

    onWarehouseChange(ev) {
        this.state.warehouseId = ev.target.value;
        this.state.offset = 0;
        this.fetchData();
    }

    filterByType(type) {
        this.state.eventTypeFilter = type;
        this.state.offset = 0;
        this.fetchData();
    }

    async prevPage() {
        if (this.state.offset > 0) {
            this.state.offset = Math.max(0, this.state.offset - this.state.pageSize);
            await this.fetchData();
        }
    }

    async nextPage() {
        if (this.state.offset + this.state.pageSize < this.state.totalCount) {
            this.state.offset += this.state.pageSize;
            await this.fetchData();
        }
    }

    scrollToSuggestions() {
        const panel = this.suggestionsPanel.el;
        if (panel) {
            panel.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }

    // ── Event Actions ───────────────────────────────────────
    openEventDetail(ev) {
        // Mark as read
        this.orm.call("warehouse.monitor.event", "mark_events_read", [[ev.id]]);
        ev.is_read = true;

        // Open related document
        if (ev.picking_id) {
            this.actionService.doAction({
                type: "ir.actions.act_window",
                res_model: "stock.picking",
                res_id: ev.picking_id,
                views: [[false, "form"]],
                target: "current",
            });
        } else if (ev.sale_id) {
            this.actionService.doAction({
                type: "ir.actions.act_window",
                res_model: "sale.order",
                res_id: ev.sale_id,
                views: [[false, "form"]],
                target: "current",
            });
        } else if (ev.purchase_id) {
            this.actionService.doAction({
                type: "ir.actions.act_window",
                res_model: "purchase.order",
                res_id: ev.purchase_id,
                views: [[false, "form"]],
                target: "current",
            });
        }
    }

    async dismissSuggestion(eventId) {
        await this.orm.call("warehouse.monitor.event", "dismiss_suggestion", [eventId]);
        this.state.suggestions = this.state.suggestions.filter((s) => s.id !== eventId);
        this.state.kpi.suggestions_pending = Math.max(0, this.state.kpi.suggestions_pending - 1);
        this.notification.add("Đã bỏ qua đề xuất", { type: "info" });
    }

    // ── Helpers ─────────────────────────────────────────────
    getTypeIcon(eventType) {
        const icons = {
            in: "IN",
            out: "OUT",
            pick: "PICK",
            pack: "PACK",
            sale: "SO",
            purchase: "PO",
            internal: "INT",
            return: "RTN",
            inventory: "INV",
        };
        return icons[eventType] || "?";
    }

    getPriorityLabel(priority) {
        const labels = {
            urgent: "🔴 KHẨN CẤP",
            high: "🟠 CAO",
            medium: "🔵 TRUNG BÌNH",
            low: "⚪ THẤP",
        };
        return labels[priority] || priority;
    }

    formatTime(timestamp) {
        if (!timestamp) return "";
        const date = new Date(timestamp + "Z"); // UTC
        const now = new Date();
        const diff = now - date;
        const minutes = Math.floor(diff / 60000);
        const hours = Math.floor(diff / 3600000);

        if (minutes < 1) return "Vừa xong";
        if (minutes < 60) return `${minutes} phút trước`;
        if (hours < 24) return `${hours} giờ trước`;

        return date.toLocaleDateString("vi-VN", {
            day: "2-digit",
            month: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
        });
    }
}

// Register as client action
registry.category("actions").add("hlv_warehouse_monitor.dashboard", WarehouseMonitorDashboard);
