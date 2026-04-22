/** @odoo-module **/

/**
 * Delivery Planner Floating AI Chat (Custom UI, no sidebar)
 * ----------------------------------------------------------
 *  - Hiện 1 floating bubble ở góc dưới-phải khi user đang ở client action
 *    `hlv_sale_delivery_planning.dashboard`.
 *  - Click → mở panel chat custom: KHÔNG có sidebar threads.
 *  - Thread được target sẵn vào assistant cấu hình (mặc định Knowledge Bot)
 *    qua backend `hlv.delivery.suggestion.ensure_chat_thread`.
 *  - User có thể đổi assistant qua nút settings (gear icon) → lưu vào
 *    ir.config_parameter.
 *
 *  KHÔNG đụng tới bất kỳ file nào của module delivery_planner gốc.
 */

import { Component, onMounted, onWillDestroy, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { Thread } from "@mail/core/common/thread";
import { Composer } from "@mail/core/common/composer";
import { rpc } from "@web/core/network/rpc";
import { DeliveryPlannerDashboard } from "@hlv_sale_delivery_planning/components/delivery_planner/delivery_planner";

const DASHBOARD_ACTION_TAG = "hlv_sale_delivery_planning.dashboard";
const DASHBOARD_DOM_SELECTOR = ".hlv_delivery_planner_dashboard";
const STORAGE_KEY_OPEN = "hlv_dp_chat_open";
const STORAGE_KEY_SIZE = "hlv_dp_chat_size";
const ACTION_POLL_INTERVAL_MS = 500;

// ──────────────────────────────────────────────────────────────────
// Snoop filter hiện tại của Dashboard mà KHÔNG sửa file delivery_planner.js
// → patch prototype._buildFetchKwargs để stash kwargs vào module-level.
// Chat đọc biến này khi gọi skill; đồng thời debounce-push snapshot
// xuống backend (`hlv.delivery.planner.tools.set_user_dashboard_context`)
// để các tool LLM (dp_list_orders, dp_active_filter…) đọc filter đúng.
// ──────────────────────────────────────────────────────────────────
let _currentDashboardFilters = null;
let _filterPushTimer = null;
let _lastPushedFiltersJson = "";
export function getCurrentDashboardFilters() {
    return _currentDashboardFilters ? { ..._currentDashboardFilters } : null;
}
function _schedulePushFilters() {
    if (_filterPushTimer) {
        clearTimeout(_filterPushTimer);
    }
    _filterPushTimer = setTimeout(async () => {
        _filterPushTimer = null;
        try {
            const snap = _currentDashboardFilters || {};
            const json = JSON.stringify(snap);
            if (json === _lastPushedFiltersJson) return; // no-op
            _lastPushedFiltersJson = json;
            await rpc("/web/dataset/call_kw", {
                model: "hlv.delivery.planner.tools",
                method: "set_user_dashboard_context",
                args: [snap],
                kwargs: {},
            });
        } catch (err) {
            // Không phá flow Kanban nếu backend chưa restart hoặc model chưa có
            console.debug("[DP Chat] push filter ctx failed", err);
        }
    }, 800);
}
try {
    patch(DeliveryPlannerDashboard.prototype, {
        _buildFetchKwargs() {
            const kwargs = super._buildFetchKwargs(...arguments);
            try {
                _currentDashboardFilters = kwargs;
                _schedulePushFilters();
            } catch (e) {}
            return kwargs;
        },
    });
} catch (e) {
    console.warn("[DP Chat] Could not patch DeliveryPlannerDashboard for filter snoop", e);
}

export class DeliveryPlannerFloatingChat extends Component {
    static template = "hlv_sale_delivery_planning.FloatingChat";
    static components = { Thread, Composer };
    static props = {};

    setup() {
        this.actionService = useService("action");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.llmStore = useState(useService("llm.store"));
        this.mailStore = useState(useService("mail.store"));

        let savedSize = { width: 460, height: 640 };
        try {
            const raw = browser.localStorage.getItem(STORAGE_KEY_SIZE);
            if (raw) {
                const parsed = JSON.parse(raw);
                if (parsed && parsed.width && parsed.height) {
                    savedSize = parsed;
                }
            }
        } catch (e) {}

        this.state = useState({
            isOnDashboard: false,
            isOpen: browser.localStorage.getItem(STORAGE_KEY_OPEN) === "1",
            isInitializing: false,
            initError: null,
            // Active thread (loaded via backend ensure_chat_thread)
            threadId: null,
            threadName: "",
            assistantId: null,
            assistantName: "",
            modelName: "",
            providerName: "",
            // Skill ops
            isPreparingSkill: false,
            skillError: null,
            // Settings (assistant picker)
            isSettingsOpen: false,
            assistantsList: [],
            isLoadingAssistants: false,
            // Resize
            width: savedSize.width,
            height: savedSize.height,
        });

        onMounted(() => {
            this.state.isOnDashboard = this._checkIsOnDashboard();
            this._pollHandle = browser.setInterval(() => {
                const onDash = this._checkIsOnDashboard();
                if (onDash !== this.state.isOnDashboard) {
                    this.state.isOnDashboard = onDash;
                }
            }, ACTION_POLL_INTERVAL_MS);
            if (this.state.isOpen && this.state.isOnDashboard) {
                // Reload page với chat đang mở → vẫn coi là "phiên mới"
                // (thread cũ đã được archive lúc close hoặc reload trước đó).
                this._initChat({ forceNew: true });
            }
        });

        onWillDestroy(() => {
            if (this._pollHandle) {
                browser.clearInterval(this._pollHandle);
            }
            this._stopResize();
        });
    }

    // ──────────────────────────────────────────────────────────────────
    // Dashboard detection (poll-based)
    // ──────────────────────────────────────────────────────────────────
    _checkIsOnDashboard() {
        try {
            const ctrl = this.actionService.currentController;
            if (ctrl && ctrl.action && ctrl.action.tag === DASHBOARD_ACTION_TAG) {
                return true;
            }
        } catch (e) {}
        try {
            return !!document.querySelector(DASHBOARD_DOM_SELECTOR);
        } catch (e) {
            return false;
        }
    }

    // ──────────────────────────────────────────────────────────────────
    // Chat init
    // ──────────────────────────────────────────────────────────────────
    async _initChat({ forceNew = false } = {}) {
        if (this.state.isInitializing) return;
        this.state.isInitializing = true;
        this.state.initError = null;
        try {
            await Promise.all([
                this.mailStore.isReady,
                this.llmStore.isReady,
            ]);

            const setup = await this.orm.call(
                "hlv.delivery.suggestion",
                "ensure_chat_thread",
                [],
                { force_new: forceNew },
            );

            this.state.threadId = setup.thread_id;
            this.state.threadName = setup.thread_name;
            this.state.assistantId = setup.assistant_id;
            this.state.assistantName = setup.assistant_name;
            this.state.modelName = setup.model_name;
            this.state.providerName = setup.provider_name;

            // Đảm bảo thread có trong mailStore
            await this.llmStore.selectThread(setup.thread_id);
        } catch (err) {
            console.error("[DeliveryPlannerFloatingChat] init error", err);
            this.state.initError = (err && err.data && err.data.message)
                || err.message
                || _t("Không thể khởi tạo AI Chat.");
        } finally {
            this.state.isInitializing = false;
        }
    }

    get activeThread() {
        if (!this.state.threadId) return null;
        return this.mailStore.Thread.get({
            model: "llm.thread",
            id: this.state.threadId,
        });
    }

    get hasThread() {
        return !!this.activeThread;
    }

    get threadComposer() {
        return this.activeThread?.composer;
    }

    get isStreaming() {
        if (!this.state.threadId) return false;
        return this.llmStore.isStreamingThread(this.state.threadId);
    }

    get panelStyle() {
        return `width:${this.state.width}px; height:${this.state.height}px;`;
    }

    // ──────────────────────────────────────────────────────────────────
    // Open/Close + actions
    // ──────────────────────────────────────────────────────────────────
    async toggleOpen() {
        const willOpen = !this.state.isOpen;
        if (willOpen) {
            // Mỗi lần mở chat → archive thread cũ (nếu có) + tạo NEW.
            // Đáp ứng yêu cầu: "khi tắt → lưu trữ; mở lại → mới".
            this.state.isOpen = true;
            try {
                browser.localStorage.setItem(STORAGE_KEY_OPEN, "1");
            } catch (e) {}
            await this._initChat({ forceNew: true });
        } else {
            await this.closePanel();
        }
    }

    async closePanel() {
        // Archive thread hiện tại trước khi đóng để lần sau mở là phiên mới.
        const tid = this.state.threadId;
        this.state.isOpen = false;
        try {
            browser.localStorage.setItem(STORAGE_KEY_OPEN, "0");
        } catch (e) {}
        if (tid) {
            try {
                await this.orm.call(
                    "hlv.delivery.suggestion", "archive_chat_thread", [tid],
                );
            } catch (err) {
                console.warn("[DP Chat] archive thread failed", err);
            }
        }
        this.state.threadId = null;
    }

    async newChat() {
        // "+" → archive cái cũ rồi tạo mới (giống đóng-mở nhưng giữ panel).
        const oldTid = this.state.threadId;
        if (oldTid) {
            try {
                await this.orm.call(
                    "hlv.delivery.suggestion", "archive_chat_thread", [oldTid],
                );
            } catch (err) {
                console.warn("[DP Chat] archive old thread failed", err);
            }
        }
        await this._initChat({ forceNew: true });
    }

    /**
     * "Xóa" phiên chat từ góc nhìn user = archive (active=False) + clear UI.
     * Sau khi xóa → tự tạo phiên mới ngay để không trống.
     */
    async deleteChat() {
        await this.newChat();
    }

    // ──────────────────────────────────────────────────────────────────
    // Settings (assistant picker)
    // ──────────────────────────────────────────────────────────────────
    async toggleSettings() {
        this.state.isSettingsOpen = !this.state.isSettingsOpen;
        if (this.state.isSettingsOpen && this.state.assistantsList.length === 0) {
            await this._loadAssistants();
        }
    }

    async _loadAssistants() {
        this.state.isLoadingAssistants = true;
        try {
            const setup = await this.orm.call(
                "hlv.delivery.suggestion", "get_chat_setup", [],
            );
            this.state.assistantsList = setup.assistants || [];
            this.state.assistantId = setup.current_assistant_id;
            this.state.assistantName = setup.current_assistant_name;
            this.state.modelName = setup.current_model_name;
            this.state.providerName = setup.current_provider_name;
        } catch (err) {
            console.error(err);
            this.notification.add(
                _t("Không tải được danh sách Assistant."),
                { type: "danger" },
            );
        } finally {
            this.state.isLoadingAssistants = false;
        }
    }

    async pickAssistant(assistantId) {
        try {
            await this.orm.call(
                "hlv.delivery.suggestion", "set_chat_assistant", [assistantId],
            );
            this.state.isSettingsOpen = false;
            this.notification.add(
                _t("Đã đổi Assistant. Đang tạo phiên chat mới..."),
                { type: "success" },
            );
            await this._initChat({ forceNew: true });
        } catch (err) {
            console.error(err);
            this.notification.add(
                (err && err.data && err.data.message) || _t("Không đổi được Assistant."),
                { type: "danger" },
            );
        }
    }

    // ──────────────────────────────────────────────────────────────────
    // Skills — render prompt từ backend (.md template) → gửi tin nhắn
    // ──────────────────────────────────────────────────────────────────
    async _runSkill(skillKey, label) {
        if (!this.state.threadId) {
            await this._initChat();
            if (!this.state.threadId) return;
        }
        this.state.isPreparingSkill = true;
        this.state.skillError = null;
        try {
            // Snoop filter user đang dùng trên Kanban → đẩy xuống backend.
            // AI sẽ chỉ phân tích đúng đơn user đang xem (kho, tag, htgh...).
            const dashboardFilters = getCurrentDashboardFilters();
            // Bước 1: backend render prompt + post thẳng vào thread
            // (tránh nhét prompt dài vào querystring của EventSource → 414).
            await this.orm.call(
                "hlv.delivery.suggestion", "submit_skill_prompt", [],
                {
                    skill: skillKey,
                    thread_id: this.state.threadId,
                    dashboard_filters: dashboardFilters || {},
                },
            );
            // Bước 2: chỉ trigger SSE generate, KHÔNG kèm message trong URL
            await this.llmStore.startLLMStreaming(this.state.threadId, "");
        } catch (err) {
            console.error(`[Skill ${label}] error`, err);
            this.state.skillError = (err && err.data && err.data.message)
                || err.message
                || _t(`Không chạy được skill: ${label}`);
            this.notification.add(this.state.skillError, { type: "danger" });
        } finally {
            this.state.isPreparingSkill = false;
        }
    }

    runSkillDelivery() {
        return this._runSkill("delivery", "Gợi ý giao hàng");
    }

    runSkillPurchase() {
        return this._runSkill("purchase", "Gợi ý đi đơn");
    }

    // ──────────────────────────────────────────────────────────────────
    // Resize
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
        if (!this._resizing) return;
        const dx = this._resizing.startX - ev.clientX;
        const dy = this._resizing.startY - ev.clientY;
        const newW = Math.max(340, Math.min(1000, this._resizing.startW + dx));
        const newH = Math.max(380, Math.min(window.innerHeight - 80, this._resizing.startH + dy));
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
            } catch (e) {}
        }
    }
}

registry.category("main_components").add("hlv_sale_delivery_planning.FloatingChat", {
    Component: DeliveryPlannerFloatingChat,
    props: {},
});
