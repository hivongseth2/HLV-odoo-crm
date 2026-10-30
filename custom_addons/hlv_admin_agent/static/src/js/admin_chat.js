/** @odoo-module **/
/*
 * Trang trợ lý quản trị (/tro-ly-quan-tri): cột trái các cuộc chat, giữa là cuộc đang mở.
 *
 * Trình duyệt không nói chuyện với Claude: nó ghi tin vào Odoo rồi hỏi lại tới khi có câu trả lời
 * (Odoo chạy Claude trong luồng nền). Chỉ hỏi khi đang chờ trả lời — một người dùng, không cần
 * hỏi định kỳ lúc rảnh. Cuộc đang mở nằm trên URL (?c=id) để tải lại trang không mất chỗ.
 */
import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";
import { boardDocument, readFileAsBase64 } from "@hlv_product_agent/js/chat_render";
import {
    buildMessage, buildPreview, buildSessionItem, buildWelcome,
} from "@hlv_admin_agent/js/admin_chat_render";

const POLL_MS = 2000;
const POLL_MS_SLOW = 5000;
// Lượt dài (tìm web, báo giá nhiều dòng): sau ngần này thì hỏi thưa lại.
const POLL_FAST_WINDOW_MS = 30000;
// Khớp giới hạn phía server (hlv_product_agent: MAX_IMAGES_PER_MESSAGE, MAX_IMAGE_BYTES).
const MAX_IMAGES = 3;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const NOT_READY_TEXT = "Chưa khai Anthropic API key (Cài đặt > Tồn kho > Trợ lý tạo mã hàng): trợ lý chưa trả lời được.";
const MOBILE_QUERY = "(max-width: 767px)";
const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 520;
const SIDEBAR_WIDTH_KEY = "hlv_admin_agent.sidebar_width";

// localStorage có thể bị chặn (chế độ riêng tư, chính sách trình duyệt): không nhớ được thì thôi.
function loadSidebarWidth() {
    try {
        return Number(window.localStorage.getItem(SIDEBAR_WIDTH_KEY)) || null;
    } catch {
        return null;
    }
}

function saveSidebarWidth(width) {
    try {
        window.localStorage.setItem(SIDEBAR_WIDTH_KEY, String(Math.round(width)));
    } catch {
        // Không nhớ được: lần sau về độ rộng mặc định.
    }
}

publicWidget.registry.HlvAdminChat = publicWidget.Widget.extend({
    selector: ".hlv-aa-app",
    events: {
        "click .hlv-aa-new": "_onNew",
        "click .hlv-aa-toggle": "_onToggleSidebar",
        "click .hlv-aa-session": "_onPickSession",
        "click .hlv-aa-session-rename": "_onRename",
        "click .hlv-aa-session-delete": "_onDelete",
        "click .hlv-aa-send": "_onSend",
        "click .hlv-pa-option": "_onOption",
        "click .hlv-aa-msg-action": "_onOpenBoard",
        "click .hlv-aa-board-close": "_closeBoard",
        "click .hlv-aa-preview-remove": "_onRemovePreview",
        "keydown textarea": "_onKeydown",
        "input textarea": "_autosize",
        "change input[type=file]": "_onPickFiles",
        "change .hlv-aa-model": "_onPickModel",
        "pointerdown .hlv-aa-resize": "_onResizeStart",
    },

    start() {
        this.sessionId = Number(new URLSearchParams(window.location.search).get("c")) || false;
        this.lastId = 0;
        this.busy = false;
        this.sending = false;
        this.pendingImages = [];
        this.panels = new Map();
        this.userName = (this.el.querySelector(".hlv-aa-account span") || {}).textContent || "";
        this.messagesEl = this.el.querySelector(".hlv-aa-messages");
        this.scrollEl = this.el.querySelector(".hlv-aa-scroll");
        this.sessionsEl = this.el.querySelector(".hlv-aa-sessions");
        this.titleEl = this.el.querySelector(".hlv-aa-title");
        this.statusEl = this.el.querySelector(".hlv-aa-status");
        this.previewsEl = this.el.querySelector(".hlv-aa-previews");
        this.textarea = this.el.querySelector("textarea");
        this.sendBtn = this.el.querySelector(".hlv-aa-send");
        this.boardEl = this.el.querySelector(".hlv-aa-board");
        this.modelEl = this.el.querySelector(".hlv-aa-model");
        this.defaultModel = this.modelEl.value;
        if (window.matchMedia(MOBILE_QUERY).matches) {
            this.el.dataset.sidebar = "0";
        }
        this._applySidebarWidth(loadSidebarWidth());
        this._onEscape = (ev) => ev.key === "Escape" && this._closeBoard();
        document.addEventListener("keydown", this._onEscape);
        // Listener gốc trên cả trang, không qua events của widget: publicWidget bọc sự kiện bằng jQuery,
        // ev.clipboardData ở đó là undefined nên dán ảnh không bao giờ ăn. Dán ở đâu trên trang cũng nhận.
        this._onDocPaste = (ev) => this._onPaste(ev);
        document.addEventListener("paste", this._onDocPaste);
        this._loadSessions();
        this._openSession(this.sessionId);
        this._autosize();
        this.textarea.focus();
        return this._super(...arguments);
    },

    destroy() {
        clearTimeout(this.pollTimer);
        document.removeEventListener("keydown", this._onEscape);
        document.removeEventListener("paste", this._onDocPaste);
        this._super(...arguments);
    },

    // ------------------------------------------------------------------
    // Đồng bộ với Odoo
    // ------------------------------------------------------------------
    async _loadSessions() {
        try {
            const result = await rpc("/admin_agent/chat/sessions", {});
            this.sessions = result.sessions;
            this.sessionsEl.replaceChildren(...result.sessions.map((s) => buildSessionItem(s, this.sessionId)));
        } catch {
            this._renderStatus("Không tải được danh sách cuộc chat.", "error");
        }
    },

    /** Mở một cuộc (false = cuộc mới chưa gửi gì): xoá khung, nạp lại từ đầu. */
    _openSession(sessionId) {
        clearTimeout(this.pollTimer);
        this.sessionId = sessionId;
        this.lastId = 0;
        // Tin nạp lần đầu là lịch sử: không tự bật bảng của tin cũ.
        this.loaded = false;
        this.busy = false;
        this.panels.clear();
        this.messagesEl.replaceChildren();
        this._setUrl();
        this._markActive();
        this._renderStatus("", "");
        // Cuộc chưa chọn model chạy model mặc định; cuộc đã chọn thì state ghi đè ngay sau.
        this.modelEl.value = this.defaultModel;
        if (sessionId) {
            this._refresh();
        } else {
            this.titleEl.textContent = "";
            this._renderWelcome();
        }
    },

    async _refresh() {
        clearTimeout(this.pollTimer);
        const sessionId = this.sessionId;
        try {
            const state = await rpc("/admin_agent/chat/state", { session_id: sessionId, after_id: this.lastId });
            // Người dùng đã chuyển cuộc khác trong lúc chờ: bỏ kết quả cũ.
            if (sessionId === this.sessionId) {
                this._applyState(state);
            }
        } catch {
            this._renderStatus("Mất kết nối tới Odoo, đang thử lại...", "error");
            this.busy = true;
        }
        this._schedulePoll();
    },

    _schedulePoll() {
        clearTimeout(this.pollTimer);
        if (this.busy) {
            const delay = Date.now() - this.busySince < POLL_FAST_WINDOW_MS ? POLL_MS : POLL_MS_SLOW;
            this.pollTimer = setTimeout(() => this._refresh(), delay);
        }
    },

    _applyState(state) {
        if (state.session_id && state.session_id !== this.sessionId) {
            // Tin đầu tiên của cuộc mới: server vừa tạo cuộc.
            this.sessionId = state.session_id;
            this._setUrl();
        }
        this.titleEl.textContent = state.name || "";
        if (state.model && !this.sending) {
            this.modelEl.value = state.model;
        }
        let gotReply = false;
        for (const message of state.messages) {
            if (message.id <= this.lastId) {
                continue;
            }
            this._appendMessage(message);
            this.lastId = message.id;
            gotReply = gotReply || message.role !== "user";
            if (message.action && message.action.type === "panel") {
                this.panels.set(String(message.id), message.action);
                if (this.loaded) {
                    this._showBoard(message.action);
                }
            }
        }
        this.loaded = true;
        const wasBusy = this.busy;
        if (state.busy && !wasBusy) {
            this.busySince = Date.now();
        }
        this.busy = Boolean(state.busy);
        this._renderWelcome();
        this._renderTyping(state);
        if (state.error) {
            this._renderStatus(state.error, "error");
        } else {
            this._renderStatus(state.ready === false ? NOT_READY_TEXT : "", "warning");
        }
        // Cột trái: tên cuộc (đặt theo tin đầu) và chấm "đang trả lời" đổi theo.
        if (gotReply || wasBusy !== this.busy) {
            this._loadSessions();
        }
    },

    // ------------------------------------------------------------------
    // Vẽ
    // ------------------------------------------------------------------
    _appendMessage(message) {
        if (message.role === "assistant") {
            // Chỉ câu trả lời mới nhất còn nút lựa chọn: nút cũ bấm lại là trả lời câu hỏi đã qua.
            for (const box of this.messagesEl.querySelectorAll(".hlv-pa-options")) {
                box.remove();
            }
        }
        this.messagesEl.appendChild(buildMessage(message, { withOptions: true }));
        this.scrollEl.scrollTop = this.scrollEl.scrollHeight;
    },

    _renderWelcome() {
        const welcome = this.messagesEl.querySelector(".hlv-aa-welcome");
        const empty = !this.messagesEl.querySelector(".hlv-aa-msg");
        if (empty && !welcome) {
            this.messagesEl.appendChild(buildWelcome(this.userName));
        } else if (!empty && welcome) {
            welcome.remove();
        }
    },

    _renderTyping(state) {
        let typing = this.messagesEl.querySelector(".hlv-aa-typing");
        if (!state.busy) {
            typing?.remove();
            return;
        }
        if (!typing) {
            typing = document.createElement("div");
            typing.className = "hlv-aa-typing";
        }
        typing.textContent = state.processing ? "Trợ lý đang làm..." : "Đang chờ trợ lý nhận tin...";
        // Luôn nằm dưới cùng, sau tin vừa tới.
        this.messagesEl.appendChild(typing);
        this.scrollEl.scrollTop = this.scrollEl.scrollHeight;
    },

    _renderStatus(text, level) {
        this.statusEl.textContent = text || "";
        this.statusEl.dataset.level = level || "";
    },

    _renderPreviews() {
        this.previewsEl.replaceChildren(...this.pendingImages.map((image, index) => buildPreview(image, index)));
    },

    _markActive() {
        for (const item of this.sessionsEl.querySelectorAll(".hlv-aa-session")) {
            item.classList.toggle("active", Number(item.dataset.id) === this.sessionId);
        }
    },

    _setUrl() {
        const url = new URL(window.location.href);
        if (this.sessionId) {
            url.searchParams.set("c", this.sessionId);
        } else {
            url.searchParams.delete("c");
        }
        window.history.replaceState(null, "", url);
    },

    _showBoard(action) {
        this.boardEl.querySelector(".hlv-aa-board-title").textContent = action.title || "Bảng";
        this.boardEl.querySelector(".hlv-aa-board-frame").srcdoc = boardDocument(action.html || "");
        this.boardEl.dataset.open = "1";
    },

    _closeBoard() {
        this.boardEl.dataset.open = "0";
    },

    // ------------------------------------------------------------------
    // Sự kiện
    // ------------------------------------------------------------------
    _onNew() {
        this._openSession(false);
        this._closeSidebarOnMobile();
        this.textarea.focus();
    },

    _onToggleSidebar() {
        this.el.dataset.sidebar = this.el.dataset.sidebar === "0" ? "1" : "0";
    },

    _closeSidebarOnMobile() {
        if (window.matchMedia(MOBILE_QUERY).matches) {
            this.el.dataset.sidebar = "0";
        }
    },

    _onPickSession(ev) {
        if (ev.target.closest(".hlv-aa-session-tools")) {
            return;
        }
        const id = Number(ev.currentTarget.dataset.id);
        if (id !== this.sessionId) {
            this._openSession(id);
        }
        this._closeSidebarOnMobile();
    },

    async _onRename(ev) {
        ev.stopPropagation();
        const id = Number(ev.currentTarget.dataset.id);
        const current = (this.sessions || []).find((s) => s.id === id);
        const name = window.prompt("Tên cuộc chat:", current ? current.name : "");
        if (name && name.trim()) {
            await rpc("/admin_agent/chat/rename", { session_id: id, name });
            if (id === this.sessionId) {
                this.titleEl.textContent = name.trim();
            }
            this._loadSessions();
        }
    },

    async _onDelete(ev) {
        ev.stopPropagation();
        const id = Number(ev.currentTarget.dataset.id);
        if (!window.confirm("Xoá cuộc chat này? Báo giá / cơ hội đã tạo trên MISA vẫn giữ nguyên.")) {
            return;
        }
        const result = await rpc("/admin_agent/chat/delete", { session_id: id });
        if (!result.ok) {
            this._renderStatus("Chưa xoá được: trợ lý đang trả lời trong cuộc này.", "error");
            return;
        }
        if (id === this.sessionId) {
            this._openSession(false);
        }
        this._loadSessions();
    },

    _onOption(ev) {
        // Bấm lựa chọn = gửi đúng chữ trên nút như tự gõ.
        if (!this.sending) {
            this.textarea.value = ev.currentTarget.dataset.option || "";
            this._onSend();
        }
    },

    _onOpenBoard(ev) {
        const action = this.panels.get(ev.currentTarget.dataset.messageId);
        if (action) {
            this._showBoard(action);
        }
    },

    async _onSend() {
        const text = this.textarea.value.trim();
        if (this.sending || (!text && !this.pendingImages.length)) {
            return;
        }
        this.sending = true;
        this.sendBtn.disabled = true;
        try {
            const state = await rpc("/admin_agent/chat/send", {
                session_id: this.sessionId,
                text,
                images: this.pendingImages.map(({ name, mimetype, data }) => ({ name, mimetype, data })),
                after_id: this.lastId,
                model: this.modelEl.value,
            });
            if (!state.error) {
                // Chỉ xoá ô nhập khi server đã nhận: gửi hỏng thì không mất chữ.
                this.textarea.value = "";
                this._autosize();
                this._clearPendingImages();
            }
            this._applyState(state);
            this._loadSessions();
        } catch {
            this._renderStatus("Chưa gửi được, thử lại.", "error");
        } finally {
            this.sending = false;
            this.sendBtn.disabled = false;
            this._schedulePoll();
        }
    },

    _onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
            ev.preventDefault();
            this._onSend();
        }
    },

    _autosize() {
        this.textarea.style.height = "auto";
        this.textarea.style.height = this.textarea.scrollHeight + "px";
    },

    _onPaste(ev) {
        // items thay vì files: ảnh chụp màn hình (Win+Shift+S, Snipping Tool) có trình duyệt chỉ đưa qua items.
        const files = [...(ev.clipboardData?.items || [])]
            .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
            .map((item) => item.getAsFile())
            .filter(Boolean);
        if (files.length) {
            ev.preventDefault();
            this._addFiles(files);
            this.textarea.focus();
        }
    },

    async _onPickModel() {
        // Cuộc đã có thì lưu ngay để lượt sau dùng model mới; cuộc mới thì gửi kèm tin đầu tiên.
        if (this.sessionId) {
            await rpc("/admin_agent/chat/model", { session_id: this.sessionId, model: this.modelEl.value });
        }
    },

    _applySidebarWidth(width) {
        if (width) {
            this.el.style.setProperty("--aa-sidebar-width", `${width}px`);
        }
    },

    /** Kéo mép phải cột trái để đổi độ rộng; nhớ trên máy này. */
    _onResizeStart(ev) {
        ev.preventDefault();
        const handle = ev.currentTarget;
        handle.setPointerCapture(ev.pointerId);
        this.el.classList.add("hlv-aa-resizing");
        let width = null;
        const onMove = (moveEv) => {
            width = Math.min(Math.max(moveEv.clientX, SIDEBAR_MIN), SIDEBAR_MAX);
            this._applySidebarWidth(width);
        };
        const onUp = () => {
            handle.removeEventListener("pointermove", onMove);
            handle.removeEventListener("pointerup", onUp);
            handle.removeEventListener("pointercancel", onUp);
            this.el.classList.remove("hlv-aa-resizing");
            if (width) {
                saveSidebarWidth(width);
            }
        };
        handle.addEventListener("pointermove", onMove);
        handle.addEventListener("pointerup", onUp);
        handle.addEventListener("pointercancel", onUp);
    },

    _onPickFiles(ev) {
        this._addFiles([...ev.target.files]);
        // Cho phép chọn lại đúng file vừa bỏ.
        ev.target.value = "";
    },

    async _addFiles(files) {
        for (const file of files) {
            if (this.pendingImages.length >= MAX_IMAGES) {
                this._renderStatus(`Mỗi tin gửi tối đa ${MAX_IMAGES} ảnh.`, "error");
                break;
            }
            if (!file.type.startsWith("image/")) {
                continue;
            }
            if (file.size > MAX_IMAGE_BYTES) {
                this._renderStatus(`Ảnh ${file.name} quá 5 MB.`, "error");
                continue;
            }
            this.pendingImages.push({
                name: file.name || "anh.png",
                mimetype: file.type,
                data: await readFileAsBase64(file),
                previewUrl: URL.createObjectURL(file),
            });
        }
        this._renderPreviews();
    },

    _onRemovePreview(ev) {
        const [removed] = this.pendingImages.splice(Number(ev.currentTarget.dataset.index), 1);
        if (removed) {
            URL.revokeObjectURL(removed.previewUrl);
        }
        this._renderPreviews();
    },

    _clearPendingImages() {
        for (const image of this.pendingImages) {
            URL.revokeObjectURL(image.previewUrl);
        }
        this.pendingImages = [];
        this._renderPreviews();
    },
});
