/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

const REFRESH_INTERVAL_SEC = 15;

export class WarehouseQueueScreen extends Component {
    static template = "hlv_warehouse_monitor.QueueScreen";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            isLoading: true,
            warehouseId: "all",
            pickQueue: [],
            packQueue: [],
            pickWaitingCount: 0,
            packWaitingCount: 0,
            warehouses: [],
            clockTime: "",
            countdownSec: REFRESH_INTERVAL_SEC,
        });

        this._refreshTimer = null;
        this._clockTimer = null;
        this._countdownTimer = null;

        onWillStart(async () => {
            await this.fetchData();
            this._startClock();
            this._startRefreshCountdown();
        });

        onWillUnmount(() => {
            clearInterval(this._refreshTimer);
            clearInterval(this._clockTimer);
            clearInterval(this._countdownTimer);
        });
    }

    // ── Data ────────────────────────────────────────────────
    async fetchData() {
        try {
            const result = await this.orm.call(
                "warehouse.monitor.event",
                "get_queue_screen_data",
                [],
                { warehouse_id: this.state.warehouseId }
            );
            this.state.pickQueue = result.pick_queue || [];
            this.state.packQueue = result.pack_queue || [];
            this.state.pickWaitingCount = result.pick_waiting_count || 0;
            this.state.packWaitingCount = result.pack_waiting_count || 0;
            this.state.warehouses = result.warehouses || [];
            this.state.isLoading = false;
        } catch (err) {
            console.error("[HLV Queue] Error fetching queue data:", err);
            this.state.isLoading = false;
            this.notification.add("Lỗi tải hàng đợi", { type: "danger" });
        }
    }

    async silentRefresh() {
        try {
            const result = await this.orm.call(
                "warehouse.monitor.event",
                "get_queue_screen_data",
                [],
                { warehouse_id: this.state.warehouseId }
            );
            const prevPickCount = this.state.pickQueue.length;
            const prevPackCount = this.state.packQueue.length;
            this.state.pickQueue = result.pick_queue || [];
            this.state.packQueue = result.pack_queue || [];
            this.state.pickWaitingCount = result.pick_waiting_count || 0;
            this.state.packWaitingCount = result.pack_waiting_count || 0;

            // Notify if new items appeared
            if (result.pick_queue.length > prevPickCount) {
                this.notification.add(
                    `📥 ${result.pick_queue.length - prevPickCount} đơn PICK mới`,
                    { type: "info", sticky: false }
                );
            }
            if (result.pack_queue.length > prevPackCount) {
                this.notification.add(
                    `📦 ${result.pack_queue.length - prevPackCount} đơn PACK mới`,
                    { type: "info", sticky: false }
                );
            }
        } catch {
            // Silent fail
        }
    }

    // ── Clock & Countdown ───────────────────────────────────
    _startClock() {
        const tick = () => {
            const now = new Date();
            this.state.clockTime = now.toLocaleTimeString("vi-VN", {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
                hour12: false,
            });
        };
        tick();
        this._clockTimer = setInterval(tick, 1000);
    }

    _startRefreshCountdown() {
        this.state.countdownSec = REFRESH_INTERVAL_SEC;
        this._countdownTimer = setInterval(() => {
            this.state.countdownSec -= 1;
            if (this.state.countdownSec <= 0) {
                this.state.countdownSec = REFRESH_INTERVAL_SEC;
                this.silentRefresh();
            }
        }, 1000);
    }

    // ── User Actions ────────────────────────────────────────
    onWarehouseChange(ev) {
        this.state.warehouseId = ev.target.value;
        this.state.isLoading = true;
        this.fetchData();
    }

    openPicking(pickingId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            res_id: pickingId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    toggleFullscreen() {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen().catch(() => {});
        } else {
            document.exitFullscreen().catch(() => {});
        }
    }

    // ── Helpers ─────────────────────────────────────────────
    formatQueueDate(dateStr) {
        if (!dateStr) return "";
        const date = new Date(dateStr + "Z");
        return date.toLocaleDateString("vi-VN", {
            day: "2-digit",
            month: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
        });
    }
}

registry.category("actions").add("hlv_warehouse_monitor.queue_screen", WarehouseQueueScreen);
