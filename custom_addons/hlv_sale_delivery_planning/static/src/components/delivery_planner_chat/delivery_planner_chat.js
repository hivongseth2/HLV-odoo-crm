/** @odoo-module **/

/**
 * Delivery Planner Floating AI Chat
 * ----------------------------------
 * Một widget chat AI nổi (floating) nhúng vào màn hình Delivery Planner Kanban.
 * KHÔNG chỉnh sửa bất kỳ file nào của module delivery_planner.
 * Component này được đăng ký vào registry "main_components" nên luôn hiện diện
 * ở root layout, nhưng chỉ render khi user đang đứng tại client action
 * `hlv_sale_delivery_planning.dashboard`.
 *
 * Sử dụng LLMChatContainer của module `llm_thread` (đã có sẵn) để hiển thị
 * UI chat đầy đủ (sidebar threads, composer, header model/tool…).
 */

import { Component, onMounted, onWillDestroy, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { LLMChatContainer } from "@llm_thread/components/llm_chat_container/llm_chat_container";

const DASHBOARD_ACTION_TAG = "hlv_sale_delivery_planning.dashboard";
const STORAGE_KEY_OPEN = "hlv_dp_chat_open";
const STORAGE_KEY_SIZE = "hlv_dp_chat_size";

export class DeliveryPlannerFloatingChat extends Component {
    static template = "hlv_sale_delivery_planning.FloatingChat";
    static components = { LLMChatContainer };
    static props = {};

    setup() {
        this.actionService = useService("action");
        this.llmStore = useState(useService("llm.store"));
        this.mailStore = useState(useService("mail.store"));
        this.notification = useService("notification");

        // Restore last size (mặc định kích thước vừa phải)
        let savedSize = { width: 420, height: 600 };
        try {
            const raw = browser.localStorage.getItem(STORAGE_KEY_SIZE);
            if (raw) {
                const parsed = JSON.parse(raw);
                if (parsed && parsed.width && parsed.height) {
                    savedSize = parsed;
                }
            }
        } catch (e) {
            // ignore
        }

        this.state = useState({
            // Hiển thị floating button / panel chỉ khi đang ở dashboard
            isOnDashboard: this._checkIsOnDashboard(),
            // Trạng thái panel chat đang mở/đóng
            isOpen: browser.localStorage.getItem(STORAGE_KEY_OPEN) === "1",
            // Đã khởi tạo dữ liệu LLM (providers/threads) chưa
            isInitialized: false,
            isInitializing: false,
            initError: null,
            // Kích thước panel (px)
            width: savedSize.width,
            height: savedSize.height,
        });

        // Lắng nghe thay đổi route/action
        this._onActionChange = () => {
            this.state.isOnDashboard = this._checkIsOnDashboard();
        };

        onWillStart(() => {
            // Nếu mở sẵn từ session trước & đang ở dashboard → init luôn
            if (this.state.isOpen && this.state.isOnDashboard) {
                this._ensureInitialized();
            }
        });

        onMounted(() => {
            // Subscribe vào hashchange / popstate để biết action thay đổi
            browser.addEventListener("hashchange", this._onActionChange);
            browser.addEventListener("popstate", this._onActionChange);
        });

        onWillDestroy(() => {
            browser.removeEventListener("hashchange", this._onActionChange);
            browser.removeEventListener("popstate", this._onActionChange);
            this._stopResize();
        });
    }

    // ──────────────────────────────────────────────────────────────────
    // Action detection
    // ──────────────────────────────────────────────────────────────────
    _checkIsOnDashboard() {
        try {
            const ctrl = this.actionService.currentController;
            const action = ctrl && ctrl.action;
            if (!action) {
                return false;
            }
            return action.tag === DASHBOARD_ACTION_TAG;
        } catch (e) {
            return false;
        }
    }

    // ──────────────────────────────────────────────────────────────────
    // LLM init
    // ──────────────────────────────────────────────────────────────────
    async _ensureInitialized() {
        if (this.state.isInitialized || this.state.isInitializing) {
            return;
        }
        this.state.isInitializing = true;
        this.state.initError = null;
        try {
            await Promise.all([
                this.mailStore.isReady,
                this.llmStore.isReady,
            ]);

            // Nếu đang chưa có active LLM thread → chọn thread gần nhất nếu có
            const activeThread = this.mailStore.discuss?.thread;
            const isActiveLLM = activeThread && activeThread.model === "llm.thread";
            if (!isActiveLLM) {
                const threads = this.llmStore.llmThreadList;
                if (threads.length > 0) {
                    await this.llmStore.selectThread(threads[0].id);
                }
            }
            this.state.isInitialized = true;
        } catch (err) {
            console.error("[DeliveryPlannerFloatingChat] init error", err);
            this.state.initError = _t("Không thể khởi tạo AI Chat. Vui lòng thử lại.");
        } finally {
            this.state.isInitializing = false;
        }
    }

    // ──────────────────────────────────────────────────────────────────
    // Open / Close
    // ──────────────────────────────────────────────────────────────────
    async toggleOpen() {
        this.state.isOpen = !this.state.isOpen;
        try {
            browser.localStorage.setItem(STORAGE_KEY_OPEN, this.state.isOpen ? "1" : "0");
        } catch (e) {
            // ignore
        }
        if (this.state.isOpen) {
            await this._ensureInitialized();
        }
    }

    closePanel() {
        this.state.isOpen = false;
        try {
            browser.localStorage.setItem(STORAGE_KEY_OPEN, "0");
        } catch (e) {
            // ignore
        }
    }

    async createNewThread() {
        await this._ensureInitialized();
        try {
            await this.llmStore.createNewThread();
        } catch (err) {
            console.error(err);
            this.notification.add(
                _t("Không tạo được hội thoại mới."),
                { type: "danger" },
            );
        }
    }

    // ──────────────────────────────────────────────────────────────────
    // Resize (kéo góc trên-trái để thay đổi kích thước panel)
    // ──────────────────────────────────────────────────────────────────
    onResizeStart(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        this._resizing = {
            startX: ev.clientX,
            startY: ev.clientY,
            startW: this.state.width,
            startH: this.state.height,
        };
        this._onMouseMove = (e) => this._onResizeMove(e);
        this._onMouseUp = () => this._stopResize();
        browser.addEventListener("mousemove", this._onMouseMove);
        browser.addEventListener("mouseup", this._onMouseUp);
    }

    _onResizeMove(ev) {
        if (!this._resizing) {
            return;
        }
        // Kéo từ góc trên-trái → tăng width khi kéo trái, tăng height khi kéo lên
        const dx = this._resizing.startX - ev.clientX;
        const dy = this._resizing.startY - ev.clientY;
        const newW = Math.max(320, Math.min(900, this._resizing.startW + dx));
        const newH = Math.max(360, Math.min(window.innerHeight - 80, this._resizing.startH + dy));
        this.state.width = newW;
        this.state.height = newH;
    }

    _stopResize() {
        if (this._onMouseMove) {
            browser.removeEventListener("mousemove", this._onMouseMove);
            this._onMouseMove = null;
        }
        if (this._onMouseUp) {
            browser.removeEventListener("mouseup", this._onMouseUp);
            this._onMouseUp = null;
        }
        if (this._resizing) {
            this._resizing = null;
            try {
                browser.localStorage.setItem(
                    STORAGE_KEY_SIZE,
                    JSON.stringify({ width: this.state.width, height: this.state.height }),
                );
            } catch (e) {
                // ignore
            }
        }
    }

    // ──────────────────────────────────────────────────────────────────
    // Computed
    // ──────────────────────────────────────────────────────────────────
    get panelStyle() {
        return `width:${this.state.width}px; height:${this.state.height}px;`;
    }

    get hasActiveLLMThread() {
        const t = this.mailStore.discuss?.thread;
        return !!(t && t.model === "llm.thread");
    }
}

// Đăng ký vào registry main_components để widget tự render ở root.
// Component sẽ tự kiểm tra current action và chỉ hiện khi đang ở dashboard.
registry.category("main_components").add("hlv_sale_delivery_planning.FloatingChat", {
    Component: DeliveryPlannerFloatingChat,
    props: {},
});
