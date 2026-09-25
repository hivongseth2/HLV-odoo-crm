/** @odoo-module **/
/*
 * Khung chat "Tạo mã hàng" trên /search_stock.
 *
 * Trình duyệt không nói chuyện với Claude: nó chỉ ghi tin vào Odoo rồi hỏi định kỳ
 * xem có câu trả lời chưa. Agent trên máy văn phòng mới là bên lấy tin và trả lời,
 * nên câu trả lời tới trễ ít nhất bằng chu kỳ poll của agent.
 */
import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

// Đang chờ Claude thì hỏi dày để câu trả lời hiện ra ngay; rảnh thì thưa lại.
const POLL_MS_BUSY = 2000;
const POLL_MS_IDLE = 8000;
// Khớp giới hạn phía server (MAX_IMAGES_PER_MESSAGE, MAX_IMAGE_BYTES).
const MAX_IMAGES = 3;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

const WELCOME_TEXT =
    "Gửi tên hàng, mã model, hãng, thông số (kèm ảnh tem nhãn nếu có). " +
    "Trợ lý sẽ kiểm trùng trên MISA rồi đề xuất tên, mã, nhóm để anh/chị xác nhận trước khi tạo.";
const OFFLINE_TEXT =
    "Máy trợ lý đang tắt. Tin vẫn được giữ lại, máy bật lên sẽ trả lời.";

function readFileAsBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
    });
}

function formatTime(utcString) {
    if (!utcString) {
        return "";
    }
    // Odoo trả "YYYY-MM-DD HH:MM:SS" theo UTC, không kèm múi giờ.
    const date = new Date(utcString.replace(" ", "T") + "Z");
    return date.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
}

publicWidget.registry.HlvProductChat = publicWidget.Widget.extend({
    selector: ".hlv-pa-chat",
    events: {
        "click .hlv-pa-toggle": "_onToggle",
        "click .hlv-pa-close": "_onToggle",
        "click .hlv-pa-send": "_onSend",
        "click .hlv-pa-new": "_onNew",
        "click .hlv-pa-preview-remove": "_onRemovePreview",
        "keydown textarea": "_onKeydown",
        "paste textarea": "_onPaste",
        "change input[type=file]": "_onPickFiles",
    },

    start() {
        this.isOpen = false;
        this.sessionId = false;
        this.lastId = 0;
        this.busy = false;
        this.sending = false;
        this.pendingImages = [];
        this.messagesEl = this.el.querySelector(".hlv-pa-messages");
        this.statusEl = this.el.querySelector(".hlv-pa-status");
        this.previewsEl = this.el.querySelector(".hlv-pa-previews");
        this.textarea = this.el.querySelector("textarea");
        this.sendBtn = this.el.querySelector(".hlv-pa-send");
        return this._super(...arguments);
    },

    destroy() {
        clearTimeout(this.pollTimer);
        this._super(...arguments);
    },

    // ------------------------------------------------------------------
    // Đồng bộ với Odoo
    // ------------------------------------------------------------------
    async _refresh() {
        clearTimeout(this.pollTimer);
        try {
            this._applyState(await rpc("/product_agent/chat/state", { after_id: this.lastId }));
        } catch {
            this._renderStatus("Mất kết nối tới Odoo, đang thử lại...", "error");
        }
        this._schedulePoll();
    },

    _schedulePoll() {
        clearTimeout(this.pollTimer);
        if (this.isOpen) {
            this.pollTimer = setTimeout(() => this._refresh(), this.busy ? POLL_MS_BUSY : POLL_MS_IDLE);
        }
    },

    _applyState(state) {
        if (state.session_id !== this.sessionId) {
            // Cuộc hội thoại đã đổi (bấm "Cuộc mới", hoặc ở tab khác): vẽ lại từ đầu.
            const hadOld = this.sessionId !== false && this.lastId > 0;
            this.sessionId = state.session_id;
            this.lastId = 0;
            this.messagesEl.replaceChildren();
            if (hadOld) {
                this._refresh();
                return;
            }
        }
        for (const message of state.messages) {
            if (message.id > this.lastId) {
                this._appendMessage(message);
                this.lastId = message.id;
            }
        }
        this.busy = Boolean(state.busy);
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
    _appendMessage(message) {
        const item = document.createElement("div");
        item.className = `hlv-pa-msg hlv-pa-msg-${message.role}`;

        if (message.content) {
            const text = document.createElement("div");
            text.className = "hlv-pa-text";
            // textContent chứ không innerHTML: nội dung là chữ của sale và của Claude.
            text.textContent = message.content;
            item.appendChild(text);
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

        this.messagesEl.appendChild(item);
        this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
    },

    _renderWelcome() {
        const existing = this.messagesEl.querySelector(".hlv-pa-welcome");
        const hasMessages = this.messagesEl.querySelector(".hlv-pa-msg");
        if (hasMessages && existing) {
            existing.remove();
        } else if (!hasMessages && !existing) {
            const welcome = document.createElement("div");
            welcome.className = "hlv-pa-welcome";
            welcome.textContent = WELCOME_TEXT;
            this.messagesEl.appendChild(welcome);
        }
    },

    _renderTyping() {
        const existing = this.messagesEl.querySelector(".hlv-pa-typing");
        if (existing) {
            existing.remove();
        }
        if (this.busy) {
            const typing = document.createElement("div");
            typing.className = "hlv-pa-typing";
            typing.textContent = "Trợ lý đang kiểm tra...";
            // Luôn nằm cuối danh sách, dưới tin mới nhất.
            this.messagesEl.appendChild(typing);
            this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
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
    _onToggle() {
        this.isOpen = !this.isOpen;
        this.el.dataset.open = this.isOpen ? "1" : "0";
        if (this.isOpen) {
            this._refresh();
            this.textarea.focus();
        } else {
            clearTimeout(this.pollTimer);
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
            const state = await rpc("/product_agent/chat/send", {
                text,
                images: this.pendingImages.map(({ name, mimetype, data }) => ({ name, mimetype, data })),
                after_id: this.lastId,
            });
            if (!state.error) {
                // Chỉ xoá ô nhập khi server đã nhận: gửi hỏng thì sale không mất chữ.
                this.textarea.value = "";
                this._clearPendingImages();
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
            this._applyState(await rpc("/product_agent/chat/new", {}));
        } catch {
            this._renderStatus("Chưa mở được cuộc mới, anh/chị thử lại.", "error");
        }
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
