/** @odoo-module **/
/*
 * Khung chat "Trợ lý" trên /search_stock: cột phải trong container của trang, luôn mở.
 *
 * Trình duyệt không nói chuyện với Claude: nó chỉ ghi tin vào Odoo rồi hỏi định kỳ
 * xem có câu trả lời chưa. Agent trên máy văn phòng mới là bên lấy tin và trả lời,
 * nên câu trả lời tới trễ ít nhất bằng chu kỳ poll của agent.
 */
import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";
import {
    addRowAskButtons, boardDocument, buildOptions, buildWelcome, formatDateTime, formatTime, paneNote,
    readFileAsBase64, renderRich, searchUrl, waitingText,
} from "@hlv_product_agent/js/chat_render";
import { splitOptions } from "@hlv_product_agent/js/rich_text";
import {
    applyDrawerWidth, loadDrawerWidth, loadSaleKey, saveDrawerWidth, saveSaleKey,
} from "@hlv_product_agent/js/chat_storage";

// Đang chờ Claude thì hỏi dày để câu trả lời hiện ra ngay; rảnh thì thưa lại. Chờ quá
// POLL_FAST_WINDOW_MS (lượt dài: tìm web, nhiều tool) thì thưa dần, đỡ dội request lên máy chủ.
const POLL_MS_BUSY = 2000;
const POLL_MS_BUSY_SLOW = 5000;
const POLL_FAST_WINDOW_MS = 30000;
const POLL_MS_IDLE = 8000;
// Khớp giới hạn phía server (MAX_IMAGES_PER_MESSAGE, MAX_IMAGE_BYTES).
const MAX_IMAGES = 3;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

const OFFLINE_TEXT =
    "Máy trợ lý đang tắt. Tin vẫn được giữ lại, máy bật lên sẽ trả lời.";

// Khung chat dính sát mép trên (STICKY_TOP khớp product_chat.css); chỉ máy tính mới dính.
const DESKTOP_QUERY = "(min-width: 992px)";
const STICKY_TOP = 0;
const MIN_CHAT_HEIGHT = 420;

publicWidget.registry.HlvProductChat = publicWidget.Widget.extend({
    selector: ".hlv-pa-chat",
    events: {
        "click .hlv-pa-send": "_onSend",
        "click .hlv-pa-new": "_onNew",
        "click .hlv-pa-preview-remove": "_onRemovePreview",
        "keydown textarea": "_onKeydown",
        "paste textarea": "_onPaste",
        "change input[type=file]": "_onPickFiles",
        "click .hlv-pa-switch": "_onSwitchPerson",
        "click .hlv-pa-pick": "_onPickPerson",
        "pointerdown .hlv-pa-resize": "_onResizeStart",
        "click .hlv-pa-board-close": "_onBoardClose",
        "click .hlv-pa-board-max": "_onBoardMax",
        "pointerdown .hlv-pa-board-head": "_onBoardDragStart",
        "click .hlv-pa-tab": "_onTab",
        "click .hlv-pa-option": "_onOption",
        "click .hlv-pa-history-item": "_onViewSession",
        "click .hlv-pa-history-back": "_onHistoryBack",
    },

    start() {
        this.sessionId = false;
        this.lastId = 0;
        this.busy = false;
        this.sending = false;
        this.pendingImages = [];
        this.saleKey = loadSaleKey();
        this.waiting = "";
        this.messagesEl = this.el.querySelector(".hlv-pa-messages");
        this.statusEl = this.el.querySelector(".hlv-pa-status");
        this.previewsEl = this.el.querySelector(".hlv-pa-previews");
        this.textarea = this.el.querySelector("textarea");
        this.sendBtn = this.el.querySelector(".hlv-pa-send");
        applyDrawerWidth(loadDrawerWidth());
        // Khung chat dính khi cuộn: chiều cao tính lại theo vị trí thật để luôn vừa khít tới đáy
        // màn hình — cao cố định thì lúc chưa cuộn tràn khỏi màn, cuộn rồi lại hở dưới đáy.
        this._fitHeight = () => {
            if (!window.matchMedia(DESKTOP_QUERY).matches) {
                this.el.style.height = "";
                return;
            }
            const top = Math.max(this.el.getBoundingClientRect().top, STICKY_TOP);
            this.el.style.height = Math.max(window.innerHeight - top - STICKY_TOP, MIN_CHAT_HEIGHT) + "px";
        };
        window.addEventListener("scroll", this._fitHeight, { passive: true });
        window.addEventListener("resize", this._fitHeight);
        this._fitHeight();
        this._addRowAskButtons();
        // Esc đóng bảng nổi: lỡ bảng nằm chỗ khuất nút đóng thì vẫn có đường thoát.
        this._onEscape = (ev) => {
            if (ev.key === "Escape") {
                this._onBoardClose();
            }
        };
        document.addEventListener("keydown", this._onEscape);
        this._refresh();
        return this._super(...arguments);
    },

    destroy() {
        clearTimeout(this.pollTimer);
        window.removeEventListener("scroll", this._fitHeight);
        window.removeEventListener("resize", this._fitHeight);
        if (this.table) {
            this.table.removeEventListener("click", this._onRowAsk);
        }
        document.removeEventListener("keydown", this._onEscape);
        this._super(...arguments);
    },

    // ------------------------------------------------------------------
    // Đồng bộ với Odoo
    // ------------------------------------------------------------------
    async _refresh() {
        clearTimeout(this.pollTimer);
        try {
            this._applyState(await rpc("/product_agent/chat/state", {
                after_id: this.lastId,
                sale_key: this.saleKey,
            }));
        } catch {
            this._renderStatus("Mất kết nối tới Odoo, đang thử lại...", "error");
        }
        this._schedulePoll();
    },

    _schedulePoll() {
        clearTimeout(this.pollTimer);
        let delay = POLL_MS_IDLE;
        if (this.busy) {
            delay = Date.now() - this.busySince < POLL_FAST_WINDOW_MS ? POLL_MS_BUSY : POLL_MS_BUSY_SLOW;
        }
        this.pollTimer = setTimeout(() => this._refresh(), delay);
    },

    _applyState(state) {
        this._renderIdentity(state);
        if (state.identity_required) {
            // Chưa biết ai đang chat: không hiện cuộc nào, bắt chọn người trước.
            this._resetConversation();
            this.busy = false;
            this._renderStatus(state.agent_online ? "" : OFFLINE_TEXT, state.agent_online ? "" : "warning");
            return;
        }
        if (state.session_id !== this.sessionId) {
            // Cuộc hội thoại đã đổi (bấm "Cuộc mới", hoặc ở tab khác): vẽ lại từ đầu.
            const hadOld = this.sessionId !== false && this.lastId > 0;
            this._resetConversation();
            this.sessionId = state.session_id;
            if (hadOld) {
                this._refresh();
                return;
            }
        }
        // Lần đầu nạp một cuộc là lịch sử: chỉ vẽ, không chạy lệnh cũ (tải lại trang mà
        // chạy lại là trang tự nhảy lung tung). Từ lần sau mới là tin vừa tới.
        const live = this.loadedSessionId === state.session_id;
        let pendingUrl = null;
        for (const message of state.messages) {
            if (message.id > this.lastId) {
                this._appendMessage(message);
                this.lastId = message.id;
                pendingUrl = (live && searchUrl(message.action)) || pendingUrl;
                if (live && message.action && message.action.type === "panel") {
                    this._showBoard(message.action);
                }
            }
        }
        this.loadedSessionId = state.session_id;
        if (pendingUrl) {
            window.location.href = pendingUrl;
        }
        if (state.busy && !this.busy) {
            this.busySince = Date.now();
        }
        this.busy = Boolean(state.busy);
        this.waiting = waitingText(state);
        this._renderWelcome();
        this._renderTyping();
        if (state.error) {
            this._renderStatus(state.error, "error");
        } else if (!state.agent_online) {
            this._renderStatus(OFFLINE_TEXT, "warning");
        } else {
            this._renderStatus("", "");
        }
    },

    // ------------------------------------------------------------------
    // Vẽ giao diện
    // ------------------------------------------------------------------
    /**
     * Khung tin nhắn về trạng thái trống. Xoá luôn mốc "đã nạp cuộc nào": giữ mốc cũ thì khi chọn
     * lại đúng người / cuộc cũ, cả lịch sử bị coi là tin mới và lệnh cũ (mở trang, mở bảng) chạy lại.
     */
    _resetConversation() {
        this.sessionId = false;
        this.lastId = 0;
        this.loadedSessionId = false;
        this.messagesEl.replaceChildren();
    },

    _appendMessage(message) {
        if (message.role === "assistant") {
            // Chỉ câu trả lời mới nhất còn nút lựa chọn: nút cũ bấm lại là trả lời câu hỏi đã qua.
            this._clearOptions();
        }
        this.messagesEl.appendChild(this._buildMessage(message, { options: true }));
        this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
    },

    _clearOptions() {
        for (const box of this.messagesEl.querySelectorAll(".hlv-pa-options")) {
            box.remove();
        }
    },

    /**
     * Một tin nhắn. options: có dựng nút lựa chọn [[...]] của trợ lý không (xem lại lịch sử thì không).
     */
    _buildMessage(message, { options = false } = {}) {
        const item = document.createElement("div");
        item.className = `hlv-pa-msg hlv-pa-msg-${message.role}`;

        if (message.content) {
            const text = document.createElement("div");
            text.className = "hlv-pa-text";
            let choices = [];
            if (message.role === "assistant") {
                const parsed = splitOptions(message.content);
                text.appendChild(renderRich(parsed.body));
                choices = options ? parsed.options : [];
            } else {
                // textContent chứ không innerHTML: chữ sale gõ và ghi chú hệ thống để nguyên.
                text.textContent = message.content;
            }
            item.appendChild(text);
            if (choices.length) {
                item.appendChild(buildOptions(choices));
            }
        }
        if (message.action && message.action.type === "panel") {
            const reopen = document.createElement("button");
            reopen.type = "button";
            reopen.className = "hlv-pa-action";
            reopen.textContent = "Mở lại bảng";
            reopen.addEventListener("click", () => this._showBoard(message.action));
            item.appendChild(reopen);
        }
        const url = searchUrl(message.action);
        if (url) {
            const link = document.createElement("a");
            link.className = "hlv-pa-action";
            link.href = url;
            link.textContent = "Xem trên trang tra tồn";
            item.appendChild(link);
        }
        for (const imageId of message.image_ids || []) {
            const link = document.createElement("a");
            link.href = `/web/content/${imageId}`;
            link.target = "_blank";
            const img = document.createElement("img");
            img.src = `/web/image/${imageId}/240x240`;
            img.alt = "ảnh đính kèm";
            link.appendChild(img);
            item.appendChild(link);
        }
        const time = document.createElement("div");
        time.className = "hlv-pa-time";
        time.textContent = formatTime(message.date);
        item.appendChild(time);
        return item;
    },

    // ------------------------------------------------------------------
    // Tab: Trò chuyện / Lịch sử / Hàng đã tạo
    // ------------------------------------------------------------------
    _onTab(ev) {
        this._switchTab(ev.currentTarget.dataset.tab);
    },

    _switchTab(tab) {
        this.el.dataset.tab = tab;
        for (const button of this.el.querySelectorAll(".hlv-pa-tab")) {
            button.classList.toggle("active", button.dataset.tab === tab);
        }
        if (tab === "history") {
            this._loadHistory();
        } else if (tab === "created") {
            this._loadCreated();
        }
    },

    async _loadHistory() {
        const pane = this.el.querySelector(".hlv-pa-pane-history");
        pane.replaceChildren(paneNote("Đang tải..."));
        const result = await rpc("/product_agent/chat/history", { sale_key: this.saleKey });
        pane.replaceChildren();
        if (!result.sessions.length) {
            pane.appendChild(paneNote("Chưa có cuộc chat nào."));
        }
        for (const session of result.sessions) {
            const item = document.createElement("button");
            item.type = "button";
            item.className = "hlv-pa-history-item";
            item.dataset.id = session.id;
            const title = document.createElement("span");
            title.className = "hlv-pa-history-title";
            title.textContent = session.name;
            const meta = document.createElement("span");
            meta.className = "hlv-pa-history-meta";
            meta.textContent = formatDateTime(session.date) + (session.open ? " · đang mở" : "");
            item.append(title, meta);
            pane.appendChild(item);
        }
    },

    async _onViewSession(ev) {
        const pane = this.el.querySelector(".hlv-pa-pane-history");
        const result = await rpc("/product_agent/chat/view", {
            session_id: Number(ev.currentTarget.dataset.id), sale_key: this.saleKey,
        });
        pane.replaceChildren();
        const back = document.createElement("button");
        back.type = "button";
        back.className = "hlv-pa-history-back";
        back.textContent = "← " + (result.name || "Lịch sử");
        pane.appendChild(back);
        // Chỉ xem lại: dựng tin như khung chat nhưng không chạy lệnh nào trong đó.
        for (const message of result.messages) {
            pane.appendChild(this._buildMessage(message));
        }
    },

    _onHistoryBack() {
        this._loadHistory();
    },

    async _loadCreated() {
        const pane = this.el.querySelector(".hlv-pa-pane-created");
        pane.replaceChildren(paneNote("Đang tải..."));
        const result = await rpc("/product_agent/chat/created", { sale_key: this.saleKey });
        pane.replaceChildren();
        if (!result.items.length) {
            pane.appendChild(paneNote("Trợ lý chưa tạo / sửa mã nào cho anh/chị."));
        }
        for (const entry of result.items) {
            const item = document.createElement("div");
            item.className = "hlv-pa-created-item";
            const head = document.createElement("div");
            const badge = document.createElement("span");
            badge.className = `hlv-pa-created-badge hlv-pa-created-${entry.action}`;
            badge.textContent = entry.action === "create" ? "Tạo" : "Sửa";
            const code = document.createElement("a");
            code.className = "hlv-pa-created-code";
            code.href = searchUrl({ type: "search", q: entry.code || entry.new }) || "#";
            code.textContent = entry.code || entry.new || "?";
            head.append(badge, code);
            const detail = document.createElement("div");
            detail.className = "hlv-pa-created-detail";
            detail.textContent = entry.action === "create"
                ? entry.name
                : `${entry.field}: ${entry.old} → ${entry.new}`;
            const meta = document.createElement("div");
            meta.className = "hlv-pa-history-meta";
            meta.textContent = formatDateTime(entry.date);
            item.append(head, detail, meta);
            pane.appendChild(item);
        }
    },

    _renderWelcome() {
        const existing = this.messagesEl.querySelector(".hlv-pa-welcome");
        const hasMessages = this.messagesEl.querySelector(".hlv-pa-msg");
        if (hasMessages && existing) {
            existing.remove();
        } else if (!hasMessages && !existing) {
            const query = document.getElementById("real-search-q");
            this.messagesEl.appendChild(buildWelcome(query ? query.value : ""));
        }
    },

    _renderTyping() {
        const existing = this.messagesEl.querySelector(".hlv-pa-typing");
        if (existing) {
            existing.remove();
        }
        if (this.waiting) {
            const typing = document.createElement("div");
            typing.className = "hlv-pa-typing";
            typing.textContent = this.waiting;
            // Luôn nằm cuối danh sách, dưới tin mới nhất.
            this.messagesEl.appendChild(typing);
            this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
        }
    },

    _renderIdentity(state) {
        const choices = state.identity_choices || [];
        const picking = Boolean(state.identity_required);
        this.el.dataset.picking = picking ? "1" : "0";
        this.el.dataset.shared = choices.length > 1 ? "1" : "0";
        this.el.querySelector(".hlv-pa-who-name").textContent = state.identity ? state.identity.name : "";

        const list = this.el.querySelector(".hlv-pa-picker-list");
        list.replaceChildren();
        if (!picking) {
            return;
        }
        // Key cũ không còn trong danh sách (tài khoản đổi người): bỏ để khỏi gửi mãi.
        saveSaleKey("");
        this.saleKey = "";
        for (const choice of choices) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "hlv-pa-pick";
            button.dataset.key = choice.key;
            button.textContent = choice.name;
            list.appendChild(button);
        }
    },

    _renderStatus(text, level) {
        this.statusEl.textContent = text;
        this.statusEl.dataset.level = level || "";
        this.el.dataset.agentOffline = level === "warning" ? "1" : "0";
    },

    _renderPreviews() {
        this.previewsEl.replaceChildren();
        this.pendingImages.forEach((image, index) => {
            const box = document.createElement("div");
            box.className = "hlv-pa-preview";
            const img = document.createElement("img");
            img.src = image.previewUrl;
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "hlv-pa-preview-remove";
            remove.dataset.index = String(index);
            remove.textContent = "×";
            box.append(img, remove);
            this.previewsEl.appendChild(box);
        });
    },

    // ------------------------------------------------------------------
    // Ảnh đính kèm
    // ------------------------------------------------------------------
    async _addFiles(files) {
        for (const file of files) {
            if (!file.type.startsWith("image/")) {
                continue;
            }
            if (this.pendingImages.length >= MAX_IMAGES) {
                this._renderStatus(`Mỗi tin gửi tối đa ${MAX_IMAGES} ảnh.`, "error");
                break;
            }
            if (file.size > MAX_IMAGE_BYTES) {
                this._renderStatus("Ảnh quá lớn (tối đa 5 MB).", "error");
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

    _clearPendingImages() {
        for (const image of this.pendingImages) {
            URL.revokeObjectURL(image.previewUrl);
        }
        this.pendingImages = [];
        this._renderPreviews();
    },

    // ------------------------------------------------------------------
    // Sự kiện
    // ------------------------------------------------------------------
    _onResizeStart(ev) {
        ev.preventDefault();
        const handle = ev.currentTarget;
        // Khung chat ở cột phải: mép trái kéo sang trái là rộng ra.
        const right = this.el.querySelector(".hlv-pa-panel").getBoundingClientRect().right;
        let width = null;
        handle.setPointerCapture(ev.pointerId);
        document.body.classList.add("hlv-pa-resizing");
        const onMove = (moveEv) => {
            width = applyDrawerWidth(right - moveEv.clientX) || width;
        };
        const onUp = () => {
            handle.removeEventListener("pointermove", onMove);
            handle.removeEventListener("pointerup", onUp);
            handle.removeEventListener("pointercancel", onUp);
            document.body.classList.remove("hlv-pa-resizing");
            if (width) {
                saveDrawerWidth(width);
            }
        };
        handle.addEventListener("pointermove", onMove);
        handle.addEventListener("pointerup", onUp);
        handle.addEventListener("pointercancel", onUp);
    },

    // ------------------------------------------------------------------
    // Bảng trợ lý (show_panel)
    // ------------------------------------------------------------------
    _showBoard(action) {
        const board = this.el.querySelector(".hlv-pa-board");
        board.querySelector(".hlv-pa-board-title").textContent = action.title || "Trợ lý";
        // Mỗi lần mở một iframe mới, đặt sandbox + nội dung TRƯỚC khi gắn vào trang: gán lại
        // srcdoc vào khung cũ (nhất là cùng nội dung khi "Mở lại bảng") có lúc không vẽ lại,
        // khung đứng ở about:blank và trắng trơn.
        const frame = document.createElement("iframe");
        frame.className = "hlv-pa-board-frame";
        frame.title = "Bảng của trợ lý";
        // Không cho script; chỉ cho link (nguồn thông số) mở tab mới, tab đó thoát hẳn sandbox.
        frame.setAttribute("sandbox", "allow-popups allow-popups-to-escape-sandbox");
        frame.srcdoc = boardDocument(action.html || "");
        board.querySelector(".hlv-pa-board-frame").replaceWith(frame);
        board.dataset.open = "1";
    },

    _onBoardClose() {
        this.el.querySelector(".hlv-pa-board").dataset.open = "0";
    },

    _onBoardMax() {
        const board = this.el.querySelector(".hlv-pa-board");
        board.dataset.max = board.dataset.max === "1" ? "0" : "1";
    },

    _onBoardDragStart(ev) {
        if (ev.target.closest("button")) {
            return;
        }
        ev.preventDefault();
        const board = this.el.querySelector(".hlv-pa-board");
        const head = ev.currentTarget;
        const rect = board.getBoundingClientRect();
        const offsetX = ev.clientX - rect.left;
        const offsetY = ev.clientY - rect.top;
        head.setPointerCapture(ev.pointerId);
        // Iframe nuốt sự kiện chuột khi con trỏ lướt qua: tắt tạm trong lúc kéo.
        board.classList.add("hlv-pa-board-dragging");
        const onMove = (moveEv) => {
            const left = Math.min(Math.max(moveEv.clientX - offsetX, 0), window.innerWidth - 120);
            const top = Math.min(Math.max(moveEv.clientY - offsetY, 0), window.innerHeight - 40);
            board.style.left = left + "px";
            board.style.top = top + "px";
            board.style.right = "auto";
        };
        const onUp = () => {
            head.removeEventListener("pointermove", onMove);
            head.removeEventListener("pointerup", onUp);
            head.removeEventListener("pointercancel", onUp);
            board.classList.remove("hlv-pa-board-dragging");
        };
        head.addEventListener("pointermove", onMove);
        head.addEventListener("pointerup", onUp);
        head.addEventListener("pointercancel", onUp);
    },

    _onOption(ev) {
        // Bấm lựa chọn = gửi đúng chữ trên nút như sale tự gõ.
        this._sendText(ev.currentTarget.dataset.option || "");
    },

    _sendText(text) {
        if (this.sending) {
            return;
        }
        this.textarea.value = text;
        this._onSend();
    },

    /**
     * Nút ✦ trên từng dòng bảng tra tồn: sale đang nhìn mã nào thì hỏi trợ lý về đúng mã đó, khỏi
     * gõ lại mã. Bảng do website_public_inventory_18 dựng sẵn khi tải trang nên gắn một lần là đủ.
     */
    _addRowAskButtons() {
        this.table = document.getElementById("inv-table");
        if (!this.table) {
            return;
        }
        addRowAskButtons(this.table);
        this._onRowAsk = (ev) => {
            const button = ev.target.closest(".hlv-pa-row-ask");
            if (button) {
                ev.preventDefault();
                ev.stopPropagation();
                this._askAboutCode(button.dataset.code);
            }
        };
        this.table.addEventListener("click", this._onRowAsk);
    },

    _askAboutCode(code) {
        // Chỉ gửi mã: trợ lý tra tình trạng mã đó rồi tự đưa lựa chọn hợp tình huống (hết hàng thì
        // mã thay thế / NCC, còn hàng thì ai đang giữ...), thay vì một danh sách việc cố định.
        this._switchTab("chat");
        this._sendText(`Mã ${code}`);
    },

    async _onSend() {
        const text = this.textarea.value.trim();
        if (this.sending || (!text && !this.pendingImages.length)) {
            return;
        }
        this.sending = true;
        this.sendBtn.disabled = true;
        try {
            const state = await rpc("/product_agent/chat/send", {
                text,
                images: this.pendingImages.map(({ name, mimetype, data }) => ({ name, mimetype, data })),
                after_id: this.lastId,
                sale_key: this.saleKey,
            });
            if (!state.error) {
                // Chỉ xoá ô nhập khi server đã nhận: gửi hỏng thì sale không mất chữ.
                this.textarea.value = "";
                this._clearPendingImages();
                this._clearOptions();
            }
            this._applyState(state);
        } catch {
            this._renderStatus("Chưa gửi được, anh/chị thử lại.", "error");
        } finally {
            this.sending = false;
            this.sendBtn.disabled = false;
            this._schedulePoll();
        }
    },

    async _onNew() {
        if (!window.confirm("Bắt đầu cuộc mới? Trợ lý sẽ không nhớ nội dung cuộc hiện tại.")) {
            return;
        }
        try {
            this._applyState(await rpc("/product_agent/chat/new", { sale_key: this.saleKey }));
        } catch {
            this._renderStatus("Chưa mở được cuộc mới, anh/chị thử lại.", "error");
        }
    },

    _onPickPerson(ev) {
        this.saleKey = ev.currentTarget.dataset.key || "";
        saveSaleKey(this.saleKey);
        this._resetConversation();
        this._refresh();
    },

    _onSwitchPerson() {
        // Chỉ bỏ lựa chọn trên máy này; cuộc chat của người cũ vẫn giữ nguyên trên Odoo.
        this.saleKey = "";
        saveSaleKey("");
        this._resetConversation();
        this._onBoardClose();
        this._refresh();
    },

    _onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
            ev.preventDefault();
            this._onSend();
        }
    },

    _onPaste(ev) {
        const files = [...(ev.clipboardData?.files || [])].filter((f) => f.type.startsWith("image/"));
        if (files.length) {
            ev.preventDefault();
            this._addFiles(files);
        }
    },

    _onPickFiles(ev) {
        this._addFiles([...ev.target.files]);
        // Cho phép chọn lại đúng file vừa bỏ.
        ev.target.value = "";
    },

    _onRemovePreview(ev) {
        const index = Number(ev.currentTarget.dataset.index);
        const [removed] = this.pendingImages.splice(index, 1);
        if (removed) {
            URL.revokeObjectURL(removed.previewUrl);
        }
        this._renderPreviews();
    },
});
