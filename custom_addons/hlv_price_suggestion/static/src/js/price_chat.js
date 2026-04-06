/** @odoo-module **/

import { Component, useState, useRef, onMounted, markup } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { session } from "@web/session";

class PriceChatAction extends Component {
    static template = "hlv_price_suggestion.PriceChatAction";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            sessions: [],
            currentSessionId: null,
            messages: [],
            inputText: "",
            loading: false,
            sidebarOpen: true,
            uploadingFile: false,
        });

        this.chatBodyRef = useRef("chatBody");
        this.fileInputRef = useRef("fileInput");

        onMounted(() => {
            this._loadSessions();
        });
    }

    // ── Sessions ──
    async _loadSessions() {
        const sessions = await this.orm.searchRead(
            "price.chat.session",
            [["user_id", "=", session.uid]],
            ["id", "name", "create_date"],
            { order: "create_date desc", limit: 50 },
        );
        this.state.sessions = sessions;
    }

    async onNewSession() {
        const sessionId = await this.orm.create("price.chat.session", [{}]);
        await this._loadSessions();
        this.state.currentSessionId = sessionId;
        this.state.messages = [];
    }

    async onSelectSession(sessionId) {
        this.state.currentSessionId = sessionId;
        await this._loadMessages(sessionId);
    }

    async onDeleteSession(ev, sessionId) {
        ev.stopPropagation();
        await this.orm.unlink("price.chat.session", [sessionId]);
        if (this.state.currentSessionId === sessionId) {
            this.state.currentSessionId = null;
            this.state.messages = [];
        }
        await this._loadSessions();
    }

    // ── Messages ──
    async _loadMessages(sessionId) {
        const messages = await this.orm.searchRead(
            "price.chat.message",
            [["session_id", "=", sessionId]],
            ["id", "role", "content", "create_date"],
            { order: "create_date asc" },
        );
        this.state.messages = messages;
        this._scrollToBottom();
    }

    onInputKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.onSendMessage();
        }
    }

    async onSendMessage() {
        const text = this.state.inputText.trim();
        if (!text || this.state.loading) return;

        if (!this.state.currentSessionId) {
            const sessionId = await this.orm.create("price.chat.session", [{}]);
            this.state.currentSessionId = sessionId;
            await this._loadSessions();
        }

        this.state.messages.push({
            id: Date.now(),
            role: "user",
            content: text,
            create_date: new Date().toISOString(),
        });
        this.state.inputText = "";
        this._scrollToBottom();

        await this._callAI(text);
    }

    async _callAI(userText) {
        const loadingId = Date.now() + 1;
        this.state.messages.push({
            id: loadingId,
            role: "assistant",
            content: "",
            _loading: true,
            create_date: new Date().toISOString(),
        });
        this.state.loading = true;
        this._scrollToBottom();

        try {
            const result = await this.orm.call(
                "price.chat.session",
                "rpc_send_message",
                [this.state.currentSessionId, userText],
            );

            const idx = this.state.messages.findIndex((m) => m.id === loadingId);
            if (idx >= 0) this.state.messages.splice(idx, 1);

            this.state.messages.push({
                id: Date.now() + 2,
                role: "assistant",
                content: result.ai_response,
                create_date: new Date().toISOString(),
            });

            await this._loadSessions();
        } catch (error) {
            const idx = this.state.messages.findIndex((m) => m.id === loadingId);
            if (idx >= 0) this.state.messages.splice(idx, 1);
            this.notification.add(
                error.message || _t("Lỗi khi gọi AI. Vui lòng thử lại."),
                { type: "danger" },
            );
        } finally {
            this.state.loading = false;
            this._scrollToBottom();
        }
    }

    // ── Excel Upload ──
    onClickUpload() {
        if (this.fileInputRef.el) {
            this.fileInputRef.el.click();
        }
    }

    async onFileSelected(ev) {
        const file = ev.target.files && ev.target.files[0];
        if (!file) return;
        ev.target.value = "";

        if (!this.state.currentSessionId) {
            const sessionId = await this.orm.create("price.chat.session", [{}]);
            this.state.currentSessionId = sessionId;
            await this._loadSessions();
        }

        // Read file as base64
        const reader = new FileReader();
        reader.onload = async (e) => {
            const base64 = e.target.result.split(",")[1];
            this.state.messages.push({
                id: Date.now(),
                role: "user",
                content: `📎 Đã tải file: ${file.name}\nĐang phân tích mã sản phẩm và đề xuất giá...`,
                create_date: new Date().toISOString(),
            });
            this._scrollToBottom();

            try {
                await this._callAIExcel(base64, file.name);
            } catch (error) {
                this.notification.add(
                    error.message || _t("Lỗi khi xử lý file Excel."),
                    { type: "danger" },
                );
            }
        };
        reader.readAsDataURL(file);
    }

    async _callAIExcel(base64Data, fileName) {
        const loadingId = Date.now() + 1;
        this.state.messages.push({
            id: loadingId,
            role: "assistant",
            content: "",
            _loading: true,
            create_date: new Date().toISOString(),
        });
        this.state.loading = true;
        this._scrollToBottom();

        try {
            const result = await this.orm.call(
                "price.chat.session",
                "rpc_process_excel",
                [this.state.currentSessionId, base64Data, fileName],
            );

            const idx = this.state.messages.findIndex((m) => m.id === loadingId);
            if (idx >= 0) this.state.messages.splice(idx, 1);

            this.state.messages.push({
                id: Date.now() + 2,
                role: "assistant",
                content: result.ai_response,
                create_date: new Date().toISOString(),
            });

            await this._loadSessions();
        } catch (error) {
            const idx = this.state.messages.findIndex((m) => m.id === loadingId);
            if (idx >= 0) this.state.messages.splice(idx, 1);
            this.notification.add(
                error.message || _t("Lỗi khi xử lý file."),
                { type: "danger" },
            );
        } finally {
            this.state.loading = false;
            this._scrollToBottom();
        }
    }

    // ── Excel Export ──
    onExportExcel() {
        if (!this.state.currentSessionId) return;
        window.open(`/price_chat/export_excel/${this.state.currentSessionId}`, "_blank");
    }

    // ── Market Crawl ──
    async onCrawlMarket() {
        if (this.state.loading) return;
        if (!this.state.currentSessionId) {
            const sessionId = await this.orm.create("price.chat.session", [{}]);
            this.state.currentSessionId = sessionId;
            await this._loadSessions();
        }

        const text = "Crawl giá thị trường cho các sản phẩm đã hỏi trong phiên này và đề xuất giá cạnh tranh.";
        this.state.messages.push({
            id: Date.now(),
            role: "user",
            content: text,
            create_date: new Date().toISOString(),
        });
        this._scrollToBottom();
        await this._callAI(text);
    }

    // ── Helpers ──
    _scrollToBottom() {
        setTimeout(() => {
            const el = this.chatBodyRef.el;
            if (el) el.scrollTop = el.scrollHeight;
        }, 100);
    }

    toggleSidebar() {
        this.state.sidebarOpen = !this.state.sidebarOpen;
    }

    formatTime(dateStr) {
        if (!dateStr) return "";
        const d = new Date(dateStr);
        return d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
    }

    formatDate(dateStr) {
        if (!dateStr) return "";
        const d = new Date(dateStr);
        return d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" });
    }

    /**
     * Convert markdown-like text to safe HTML markup for OWL t-out.
     */
    formatContent(text) {
        if (!text) return "";
        let html = text;
        // Escape HTML entities
        html = html.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        // Bold
        html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
        // Headers
        html = html.replace(/^### (.+)$/gm, '<div class="pc-h3">$1</div>');
        html = html.replace(/^## (.+)$/gm, '<div class="pc-h2">$1</div>');
        html = html.replace(/^# (.+)$/gm, '<div class="pc-h1">$1</div>');
        // Bullet lists
        html = html.replace(/^[-•] (.+)$/gm, '<div class="pc-li">&bull; $1</div>');
        // Numbered lists
        html = html.replace(/^(\d+)\. (.+)$/gm, '<div class="pc-li">$1. $2</div>');
        // Newlines
        html = html.replace(/\n/g, "<br/>");
        return markup(html);
    }
}

registry.category("actions").add("price_chat_action", PriceChatAction);
