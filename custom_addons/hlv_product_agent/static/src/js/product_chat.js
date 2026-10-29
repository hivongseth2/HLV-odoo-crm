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

// Người đang chat trên tài khoản dùng chung. Nhớ theo trình duyệt vì mỗi sale ngồi một
// máy; storage có thể bị chặn (chế độ ẩn danh) -> không nhớ được thì hỏi lại, không lỗi.
const SALE_KEY_STORAGE = "hlv_pa_sale_key";

function loadSaleKey() {
    try {
        return window.localStorage.getItem(SALE_KEY_STORAGE) || "";
    } catch {
        return "";
    }
}

function saveSaleKey(key) {
    try {
        if (key) {
            window.localStorage.setItem(SALE_KEY_STORAGE, key);
        } else {
            window.localStorage.removeItem(SALE_KEY_STORAGE);
        }
    } catch {
        // Không lưu được: lần sau mở trang hỏi lại, chấp nhận được.
    }
}

// Độ rộng khung chat kéo bằng chuột, nhớ theo trình duyệt. Chặn hai đầu để không kéo mất
// ngăn kéo hay che hết bảng tra tồn.
const DRAWER_WIDTH_STORAGE = "hlv_pa_drawer_width";
const DRAWER_MIN_WIDTH = 300;
const DRAWER_MAX_RATIO = 0.45;

/**
 * Độ rộng hợp lệ (px). Nhận số bất kỳ; biên: không phải số -> null.
 */
function clampDrawerWidth(width) {
    const value = Number(width);
    if (!Number.isFinite(value) || value <= 0) {
        return null;
    }
    return Math.round(Math.min(Math.max(value, DRAWER_MIN_WIDTH), window.innerWidth * DRAWER_MAX_RATIO));
}

function applyDrawerWidth(width) {
    const value = clampDrawerWidth(width);
    if (value) {
        document.documentElement.style.setProperty("--pa-drawer-width", value + "px");
    }
    return value;
}

function loadDrawerWidth() {
    try {
        return window.localStorage.getItem(DRAWER_WIDTH_STORAGE);
    } catch {
        return null;
    }
}

function saveDrawerWidth(width) {
    try {
        window.localStorage.setItem(DRAWER_WIDTH_STORAGE, String(width));
    } catch {
        // Không lưu được: lần sau về độ rộng mặc định.
    }
}

// Khung HTML cho bảng trợ lý: style nền tảng để bảng Claude dựng nhìn gọn dù nó quên style.
const BOARD_BASE_CSS =
    "body{margin:0;padding:14px;font:13px/1.45 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;" +
    "color:#1f2933;background:#fff}table{border-collapse:collapse;width:100%;margin:6px 0}" +
    "th,td{border:1px solid #d9dee3;padding:5px 8px;vertical-align:top}" +
    "th{background:#e8f1fb;color:#0d4c8c;text-align:left}h1,h2,h3{color:#0d4c8c;margin:8px 0}";

function boardDocument(html) {
    return `<!doctype html><html><head><meta charset="utf-8"><style>${BOARD_BASE_CSS}</style>` +
        `</head><body>${html}</body></html>`;
}

/**
 * URL trang tra tồn tìm đúng từ khoá, giữ nguyên trang đang mở (vd /en/search_stock).
 * Nhận: lệnh {type: 'search', q}. Biên: lệnh lạ / thiếu q -> null.
 */
function searchUrl(action) {
    if (!action || action.type !== "search" || !action.q) {
        return null;
    }
    const url = new URL(window.location.href);
    url.search = "";
    url.searchParams.set("q", action.q);
    return url.toString();
}

/**
 * Dòng báo trạng thái chờ dưới tin cuối.
 * Nhận: state từ server. Trả: chuỗi, hoặc "" khi không chờ gì.
 */
function waitingText(state) {
    if (state.processing) {
        return "Trợ lý đang kiểm tra...";
    }
    if (!state.busy) {
        return "";
    }
    if (state.queue_ahead) {
        return `Đang xếp hàng: trước anh/chị còn ${state.queue_ahead} cuộc chat.`;
    }
    return "Đang chờ trợ lý nhận tin...";
}

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
        // Khung chat luôn mở, là cột phải trong container của trang tra tồn: gắn class để
        // product_chat.css chia lưới hai cột (portal không có khung chat thì trang giữ nguyên).
        this.el.parentElement.classList.add("hlv-pa-host");
        document.body.classList.add("hlv-pa-embedded");
        this._refresh();
        return this._super(...arguments);
    },

    destroy() {
        clearTimeout(this.pollTimer);
        document.body.classList.remove("hlv-pa-embedded");
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
        this.pollTimer = setTimeout(() => this._refresh(), this.busy ? POLL_MS_BUSY : POLL_MS_IDLE);
    },

    _applyState(state) {
        this._renderIdentity(state);
        if (state.identity_required) {
            // Chưa biết ai đang chat: không hiện cuộc nào, bắt chọn người trước.
            this.sessionId = false;
            this.lastId = 0;
            this.busy = false;
            this.messagesEl.replaceChildren();
            this._renderStatus(state.agent_online ? "" : OFFLINE_TEXT, state.agent_online ? "" : "warning");
            return;
        }
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
        frame.setAttribute("sandbox", "");
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
        this.sessionId = false;
        this.lastId = 0;
        this.messagesEl.replaceChildren();
        this._refresh();
    },

    _onSwitchPerson() {
        // Chỉ bỏ lựa chọn trên máy này; cuộc chat của người cũ vẫn giữ nguyên trên Odoo.
        this.saleKey = "";
        saveSaleKey("");
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
