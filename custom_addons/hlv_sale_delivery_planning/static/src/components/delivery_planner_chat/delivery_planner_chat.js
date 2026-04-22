/** @odoo-module **/

/**
 * Delivery Planner Floating AI Chat
 * ----------------------------------
 * Floating widget chat AI nhúng vào màn hình Delivery Planner Kanban,
 * KHÔNG chỉnh sửa file nào của module delivery_planner.
 *
 * Đăng ký vào registry "main_components" để Web Client tự render ở root.
 * Widget tự kiểm tra:
 *   - Action hiện tại có phải `hlv_sale_delivery_planning.dashboard` không
 *     (poll 500ms vì action service không reactive).
 *   - DOM `.hlv_delivery_planner_dashboard` có tồn tại không (fallback).
 *
 * Skills:
 *   1. "Gợi ý đi đơn (mua)"  — placeholder, chưa cấu hình logic.
 *   2. "Gợi ý giao hàng"     — gom data context (ĐÃ ĐÓNG, CHỜ NHẬN GIAO)
 *      từ backend `hlv.delivery.suggestion.get_delivery_suggestion_context`
 *      rồi nhét vào prompt user gửi lên thread đang active.
 */

import { Component, onMounted, onWillDestroy, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { LLMChatContainer } from "@llm_thread/components/llm_chat_container/llm_chat_container";

const DASHBOARD_ACTION_TAG = "hlv_sale_delivery_planning.dashboard";
const DASHBOARD_DOM_SELECTOR = ".hlv_delivery_planner_dashboard";
const STORAGE_KEY_OPEN = "hlv_dp_chat_open";
const STORAGE_KEY_SIZE = "hlv_dp_chat_size";
const ACTION_POLL_INTERVAL_MS = 500;

export class DeliveryPlannerFloatingChat extends Component {
    static template = "hlv_sale_delivery_planning.FloatingChat";
    static components = { LLMChatContainer };
    static props = {};

    setup() {
        this.actionService = useService("action");
        this.orm = useService("orm");
        this.llmStore = useState(useService("llm.store"));
        this.mailStore = useState(useService("mail.store"));
        this.notification = useService("notification");

        // Restore last size
        let savedSize = { width: 460, height: 640 };
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
            isOnDashboard: false,
            isOpen: browser.localStorage.getItem(STORAGE_KEY_OPEN) === "1",
            isInitialized: false,
            isInitializing: false,
            initError: null,
            width: savedSize.width,
            height: savedSize.height,
            // Skills
            isPreparingSkill: false,
            skillError: null,
        });

        onWillStart(() => {
            this.state.isOnDashboard = this._checkIsOnDashboard();
            if (this.state.isOpen && this.state.isOnDashboard) {
                this._ensureInitialized();
            }
        });

        onMounted(() => {
            // Poll because actionService.currentController is NOT reactive
            this._pollHandle = browser.setInterval(() => {
                const onDash = this._checkIsOnDashboard();
                if (onDash !== this.state.isOnDashboard) {
                    this.state.isOnDashboard = onDash;
                }
            }, ACTION_POLL_INTERVAL_MS);
        });

        onWillDestroy(() => {
            if (this._pollHandle) {
                browser.clearInterval(this._pollHandle);
            }
            this._stopResize();
        });
    }

    // ──────────────────────────────────────────────────────────────────
    // Dashboard detection (poll-based since action svc isn't reactive)
    // ──────────────────────────────────────────────────────────────────
    _checkIsOnDashboard() {
        // 1) Check current action tag
        try {
            const ctrl = this.actionService.currentController;
            const action = ctrl && ctrl.action;
            if (action && action.tag === DASHBOARD_ACTION_TAG) {
                return true;
            }
        } catch (e) {
            // ignore
        }
        // 2) Fallback: DOM check
        try {
            return !!document.querySelector(DASHBOARD_DOM_SELECTOR);
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
        } catch (e) {}
        if (this.state.isOpen) {
            await this._ensureInitialized();
        }
    }

    closePanel() {
        this.state.isOpen = false;
        try {
            browser.localStorage.setItem(STORAGE_KEY_OPEN, "0");
        } catch (e) {}
    }

    async createNewThread() {
        await this._ensureInitialized();
        try {
            await this.llmStore.createNewThread();
        } catch (err) {
            console.error(err);
            this.notification.add(_t("Không tạo được hội thoại mới."), { type: "danger" });
        }
    }

    get hasActiveLLMThread() {
        const t = this.mailStore.discuss?.thread;
        return !!(t && t.model === "llm.thread");
    }

    get activeThreadId() {
        const t = this.mailStore.discuss?.thread;
        return (t && t.model === "llm.thread") ? t.id : null;
    }

    // ──────────────────────────────────────────────────────────────────
    // Skills
    // ──────────────────────────────────────────────────────────────────
    async runSkillDelivery() {
        await this._ensureInitialized();
        if (!this.hasActiveLLMThread) {
            await this.createNewThread();
        }
        const tid = this.activeThreadId;
        if (!tid) {
            this.notification.add(
                _t("Chưa có hội thoại AI. Hãy tạo hội thoại mới rồi thử lại."),
                { type: "warning" },
            );
            return;
        }

        this.state.isPreparingSkill = true;
        this.state.skillError = null;
        try {
            const ctx = await this.orm.call(
                "hlv.delivery.suggestion",
                "get_delivery_suggestion_context",
                [],
                { history_days: 30, max_orders: 60 },
            );
            const prompt = this._buildDeliveryPrompt(ctx);
            await this.llmStore.sendLLMMessage(tid, prompt);
        } catch (err) {
            console.error("[DeliveryPlannerFloatingChat] skill delivery error", err);
            this.state.skillError = _t("Không lấy được dữ liệu đơn hàng để gợi ý.");
            this.notification.add(this.state.skillError, { type: "danger" });
        } finally {
            this.state.isPreparingSkill = false;
        }
    }

    async runSkillPurchase() {
        // Placeholder — user chưa muốn viết logic
        this.notification.add(
            _t("Skill 'Gợi ý đi đơn' đang chờ cấu hình nghiệp vụ. Sẽ bổ sung sau."),
            { type: "info" },
        );
    }

    /**
     * Build a structured Vietnamese prompt from backend context.
     */
    _buildDeliveryPrompt(ctx) {
        const orders = ctx.orders || [];
        const routes = ctx.route_summary || [];
        const history = ctx.shipper_history || [];

        const ordersBrief = orders.map((o, i) => {
            const products = (o.products || []).map(p =>
                `${p.name} x${p.qty}${p.uom ? ' ' + p.uom : ''}`
            ).join('; ');
            return [
                `${i + 1}. [${o.name}] ${o.partner_name}`,
                `   • Địa chỉ: ${o.address || '(thiếu)'}`,
                `   • Tuyến/Tag: ${o.route || '(chưa phân)'} | HTGH: ${o.htgh || '(chưa)'}`,
                `   • Hẹn giao: ${o.commitment_date || o.scheduled_date || '(chưa)'} | Kho: ${o.warehouse}`,
                `   • Giá trị: ${(o.amount_total || 0).toLocaleString('vi-VN')} ${o.currency || 'VND'}`,
                `   • Shipper hiện tại: ${o.shipper_name || '(chưa gán)'}`,
                `   • Sản phẩm (${o.product_count}): ${products || '(không có)'}`,
                `   • Phiếu: ${(o.picking_names || []).join(', ')}`,
            ].join('\n');
        }).join('\n\n');

        const routesBrief = routes.length
            ? routes.map(r => `   - ${r.route}: ${r.order_count} đơn, tổng ${(r.total_value || 0).toLocaleString('vi-VN')}đ`).join('\n')
            : '   (không có dữ liệu tuyến)';

        const historyBrief = history.length
            ? history.map(h => {
                const routeTop = Object.entries(h.routes || {})
                    .map(([r, c]) => `${r}(${c})`).join(', ');
                const onTimeRate = (h.on_time_count + h.late_count) > 0
                    ? Math.round(100 * h.on_time_count / (h.on_time_count + h.late_count))
                    : null;
                return `   - ${h.name}: ${h.completed_orders} đơn/${ctx.history_days}ng, ` +
                    `TB ${h.avg_delivery_hours ?? '?'}h/phiếu, ` +
                    `đúng giờ ${onTimeRate ?? '?'}%, ` +
                    `tuyến quen: ${routeTop || '(không)'}`;
            }).join('\n')
            : '   (chưa có lịch sử)';

        return [
            `[SKILL] Gợi ý giao hàng — Delivery Planner`,
            ``,
            `Bạn là AI dispatcher cho HLV. Mục tiêu:`,
            `  • Gom đơn theo tuyến / khu vực / hãng vận chuyển để giao càng nhiều đơn cho 1 chuyến càng tốt.`,
            `  • Ưu tiên đơn theo ngày hẹn giao (commitment_date), không để trễ.`,
            `  • Cân nhắc giá trị đơn (đơn giá trị lớn cần độ tin cậy cao của shipper).`,
            `  • Học từ lịch sử shipper: ai đi tuyến nào nhanh / đúng giờ → ưu tiên gán.`,
            `  • Cảnh báo các đơn nguy cơ trễ hoặc thiếu thông tin (địa chỉ, tuyến, HTGH).`,
            ``,
            `Yêu cầu output (tiếng Việt, ngắn gọn, dạng bảng/markdown):`,
            `  1. Đề xuất phân chuyến: mỗi chuyến gồm danh sách mã đơn + shipper đề cử + lý do.`,
            `  2. Cảnh báo: đơn cần xử lý gấp / dữ liệu thiếu.`,
            `  3. Ghi chú học máy: nếu thấy pattern shipper mạnh ở tuyến X → khuyến nghị.`,
            ``,
            `=== DỮ LIỆU SỐ HOÁ (do hệ thống cung cấp, ${ctx.generated_at}) ===`,
            ``,
            `>> Tổng số đơn ĐÃ ĐÓNG, CHỜ NHẬN GIAO: ${ctx.total_orders}`,
            ``,
            `>> Tóm tắt tuyến (route_summary):`,
            routesBrief,
            ``,
            `>> Lịch sử shipper ${ctx.history_days} ngày gần nhất:`,
            historyBrief,
            ``,
            `>> Chi tiết đơn:`,
            ordersBrief || '(không có đơn)',
        ].join('\n');
    }

    // ──────────────────────────────────────────────────────────────────
    // Resize (drag góc trên-trái)
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

    get panelStyle() {
        return `width:${this.state.width}px; height:${this.state.height}px;`;
    }
}

// Đăng ký vào main_components — webclient sẽ tự render. Component bên
// trong tự kiểm tra route nên không xuất hiện ở các action khác.
registry.category("main_components").add("hlv_sale_delivery_planning.FloatingChat", {
    Component: DeliveryPlannerFloatingChat,
    props: {},
});
