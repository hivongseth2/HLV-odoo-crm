/** @odoo-module **/
/*
 * Màn "Cá nhân hoá" của trang trợ lý quản trị: hướng dẫn riêng + ghi nhớ của chính người đang đăng nhập.
 *
 * Widget riêng gắn cùng khung trang với admin_chat.js: hai việc không đụng nhau (chat / cài đặt cá
 * nhân), tách ra cho mỗi file làm một việc. Trợ lý đọc những thứ này ở đầu mỗi lượt.
 */
import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.HlvAdminPersonal = publicWidget.Widget.extend({
    selector: ".hlv-aa-app",
    events: {
        "click .hlv-aa-open-personal": "_onOpen",
        "click .hlv-aa-personal-close": "_onClose",
        "click .hlv-aa-save-instructions": "_onSaveInstructions",
        "click .hlv-aa-memory-add-btn": "_onAddMemory",
        "keydown .hlv-aa-memory-text": "_onMemoryKeydown",
        "click .hlv-aa-memory-edit": "_onEditMemory",
        "click .hlv-aa-memory-delete": "_onDeleteMemory",
    },

    start() {
        this.panel = this.el.querySelector(".hlv-aa-personal");
        this.instructionsEl = this.el.querySelector(".hlv-aa-instructions");
        this.messageEl = this.el.querySelector(".hlv-aa-personal-msg");
        this.kindEl = this.el.querySelector(".hlv-aa-memory-kind");
        this.memoryTextEl = this.el.querySelector(".hlv-aa-memory-text");
        this.memoriesEl = this.el.querySelector(".hlv-aa-memories");
        this.kinds = [];
        return this._super(...arguments);
    },

    async _onOpen() {
        this.panel.dataset.open = "1";
        await this._load();
    },

    _onClose() {
        this.panel.dataset.open = "0";
    },

    async _load() {
        const data = await rpc("/admin_agent/personal/get", {});
        this.instructionsEl.value = data.instructions || "";
        if (!this.kinds.length) {
            this.kinds = data.kinds;
            this.kindEl.replaceChildren(...data.kinds.map(([code, label]) => {
                const option = document.createElement("option");
                option.value = code;
                option.textContent = label;
                return option;
            }));
        }
        this.memories = data.memories;
        this._renderMemories();
    },

    _renderMemories() {
        const labels = Object.fromEntries(this.kinds);
        if (!this.memories.length) {
            const empty = document.createElement("div");
            empty.className = "hlv-aa-muted";
            empty.textContent = "Chưa có ghi nhớ nào.";
            this.memoriesEl.replaceChildren(empty);
            return;
        }
        this.memoriesEl.replaceChildren(...this.memories.map((memory) => {
            const row = document.createElement("div");
            row.className = "hlv-aa-memory";
            const kind = document.createElement("span");
            kind.className = "hlv-aa-memory-kind-badge";
            kind.textContent = labels[memory.kind] || memory.kind;
            const text = document.createElement("span");
            text.className = "hlv-aa-memory-content";
            text.textContent = memory.content;
            row.append(kind, text);
            for (const [action, icon, title] of [["edit", "fa-pencil", "Sửa"], ["delete", "fa-trash-o", "Xoá"]]) {
                const button = document.createElement("button");
                button.type = "button";
                button.className = `hlv-aa-memory-${action}`;
                button.dataset.id = memory.id;
                button.title = title;
                const i = document.createElement("i");
                i.className = `fa ${icon}`;
                button.appendChild(i);
                row.appendChild(button);
            }
            return row;
        }));
    },

    _flash(text, isError = false) {
        this.messageEl.textContent = text;
        this.messageEl.dataset.level = isError ? "error" : "";
    },

    async _onSaveInstructions() {
        const result = await rpc("/admin_agent/personal/instructions", { instructions: this.instructionsEl.value });
        this._flash(result.ok ? "Đã lưu — trợ lý dùng từ tin kế tiếp." : result.error, !result.ok);
    },

    async _onAddMemory() {
        const content = this.memoryTextEl.value.trim();
        if (!content) {
            return;
        }
        const result = await rpc("/admin_agent/personal/memory/add", { content, kind: this.kindEl.value });
        if (!result.ok) {
            this._flash(result.error, true);
            return;
        }
        this.memoryTextEl.value = "";
        await this._load();
    },

    _onMemoryKeydown(ev) {
        if (ev.key === "Enter" && !ev.isComposing) {
            ev.preventDefault();
            this._onAddMemory();
        }
    },

    async _onEditMemory(ev) {
        const id = Number(ev.currentTarget.dataset.id);
        const memory = this.memories.find((m) => m.id === id);
        const content = window.prompt("Sửa ghi nhớ:", memory ? memory.content : "");
        if (content === null || !content.trim()) {
            return;
        }
        const result = await rpc("/admin_agent/personal/memory/update", { memory_id: id, content });
        if (!result.ok) {
            this._flash(result.error, true);
        }
        await this._load();
    },

    async _onDeleteMemory(ev) {
        if (!window.confirm("Xoá ghi nhớ này? Trợ lý sẽ không còn nhớ điều đó.")) {
            return;
        }
        await rpc("/admin_agent/personal/memory/delete", { memory_id: Number(ev.currentTarget.dataset.id) });
        await this._load();
    },
});
