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
            deliveryPlan: {
                isLoading: false,
                loaded: false,
                trips: [],
                poNotifications: [],
                totalOrders: 0,
                totalTrips: 0,
                expandedTrip: null,
            },
            aiPanel: {
                isThinking: false,
                cards: [],
                lastEventId: null,
                userQuestion: "",
            },
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
            // Load previously stored AI insights
            await this.loadAIInsights();
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
            // Anchor lastEventId so first silentRefresh doesn't re-analyze old events
            if (this.state.aiPanel.lastEventId === null && this.state.events.length > 0) {
                this.state.aiPanel.lastEventId = this.state.events[0].id;
            }
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

            // Auto-analyze if a new significant event appeared
            const SIGNIFICANT_ACTIONS = new Set(["validate", "confirm", "priority_set"]);
            const SIGNIFICANT_TYPES = new Set(["in", "pick", "pack", "out", "sale", "purchase"]);
            const latestEvent = this.state.events[0];
            if (
                latestEvent &&
                latestEvent.id !== this.state.aiPanel.lastEventId &&
                SIGNIFICANT_ACTIONS.has(latestEvent.action) &&
                SIGNIFICANT_TYPES.has(latestEvent.event_type)
            ) {
                this.state.aiPanel.lastEventId = latestEvent.id;
                this.analyzeLatestEvent(latestEvent.id);
            } else if (latestEvent) {
                this.state.aiPanel.lastEventId = latestEvent.id;
            }

            // Auto-refresh delivery plan if it was previously loaded
            if (this.state.deliveryPlan.loaded) {
                this.loadDeliveryPlan();
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

    // ── Phase 2: Delivery Planner ───────────────────────────
    async loadDeliveryPlan() {
        if (this.state.deliveryPlan.isLoading) return;
        this.state.deliveryPlan.isLoading = true;
        try {
            const result = await this.orm.call(
                "warehouse.monitor.event",
                "get_delivery_plan_suggestions",
                [],
                { warehouse_id: this.state.warehouseId }
            );
            this.state.deliveryPlan.trips = result.trips || [];
            this.state.deliveryPlan.poNotifications = result.po_notify || [];
            this.state.deliveryPlan.totalOrders = result.total_orders || 0;
            this.state.deliveryPlan.totalTrips = result.total_trips || 0;
            this.state.deliveryPlan.loaded = true;

            if ((result.po_notify || []).length > 0) {
                this.notification.add(
                    `${result.po_notify.length} PO đang về kho – chuẩn bị đóng gói!`,
                    { type: "warning", sticky: false }
                );
            }
        } catch (e) {
            console.error("[WM Planner] Delivery plan fetch error:", e);
            this.notification.add("Lỗi tải kế hoạch giao hàng", { type: "danger" });
        } finally {
            this.state.deliveryPlan.isLoading = false;
        }
    }

    toggleTripExpand(tripId) {
        this.state.deliveryPlan.expandedTrip =
            this.state.deliveryPlan.expandedTrip === tripId ? null : tripId;
    }

    // ── Phase 3: AI Assistant ────────────────────────────────

    /** Load existing (not dismissed) insights stored in Odoo DB. */
    async loadAIInsights() {
        try {
            const insights = await this.orm.call(
                "warehouse.monitor.event",
                "get_ai_insights",
                [],
                { limit: 15, warehouse_id: this.state.warehouseId }
            );
            this.state.aiPanel.cards = insights || [];
        } catch (e) {
            console.warn("[WM AI] Could not load insights:", e);
        }
    }

    /** Analyze a specific event via OpenAI and prepend result card. */
    async analyzeLatestEvent(eventId) {
        if (this.state.aiPanel.isThinking) return;
        this.state.aiPanel.isThinking = true;
        try {
            const insight = await this.orm.call(
                "warehouse.monitor.event",
                "analyze_event",
                [],
                { event_id: eventId }
            );
            if (insight && !insight.error) {
                // Prepend and cap at 15 cards
                this.state.aiPanel.cards = [insight, ...this.state.aiPanel.cards].slice(0, 15);
            } else if (insight && insight.no_key) {
                // API key not configured — silent (no spam notification)
                console.info("[WM AI] OpenAI key not configured, skipping auto-analysis.");
            } else if (insight && insight.error) {
                console.warn("[WM AI] analyze_event error:", insight.error);
            }
        } catch (e) {
            console.warn("[WM AI] analyzeLatestEvent failed:", e);
        } finally {
            this.state.aiPanel.isThinking = false;
        }
    }

    /** Send free-form user question to AI. */
    async askAI() {
        const q = (this.state.aiPanel.userQuestion || "").trim();
        if (!q) return;
        if (this.state.aiPanel.isThinking) return;

        this.state.aiPanel.userQuestion = "";
        this.state.aiPanel.isThinking = true;
        try {
            const insight = await this.orm.call(
                "warehouse.monitor.event",
                "ask_ai",
                [],
                {
                    question: q,
                    context_event_id: this.state.aiPanel.lastEventId || false,
                }
            );
            if (insight && !insight.error) {
                this.state.aiPanel.cards = [insight, ...this.state.aiPanel.cards].slice(0, 15);
            } else if (insight && insight.error) {
                this.notification.add("AI: " + insight.error, { type: "warning" });
            }
        } catch (e) {
            console.warn("[WM AI] askAI failed:", e);
            this.notification.add("Lỗi gọi AI trợ lý", { type: "danger" });
        } finally {
            this.state.aiPanel.isThinking = false;
        }
    }

    onAiQuestionInput(ev) {
        this.state.aiPanel.userQuestion = ev.target.value;
    }

    onAiQuestionKeydown(ev) {
        if (ev.key === "Enter") {
            this.askAI();
        }
    }

    /** Dismiss one insight card (hide from view + mark dismissed in DB). */
    async dismissInsight(insightId) {
        this.state.aiPanel.cards = this.state.aiPanel.cards.filter((c) => c.id !== insightId);
        try {
            await this.orm.call(
                "warehouse.monitor.event",
                "dismiss_ai_insight",
                [],
                { insight_id: insightId }
            );
        } catch {
            // non-critical
        }
    }

    /** Clear all insight cards. */
    async clearAllInsights() {
        this.state.aiPanel.cards = [];
        try {
            await this.orm.call("warehouse.monitor.event", "clear_ai_insights", [], {});
        } catch {
            // non-critical
        }
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
