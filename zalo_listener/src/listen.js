// Nghe tin nhóm + tự nối lại theo lịch của backoff.js (tắt cơ chế tự nối của zca-js: nó xoá bộ đếm ngay khi nối
// lại — đúng kiểu sự cố kẹt 17 tiếng). Mỗi lần nối lại xin Zalo gửi lại lô tin nhóm gần nhất để vá các phút "điếc"
// trước khi rớt; tin trùng tự bỏ nhờ mã tin.
"use strict";

const fs = require("fs");
const { ThreadType } = require("zca-js");
const { STABLE_MS, onClose } = require("./backoff");
const { normalizeMessage, normalizeReaction, reactionKey } = require("./normalize");

// Tên nhóm tra lại sau chừng này (đổi tên nhóm trên Zalo thì Odoo cũng đổi theo).
const GROUP_NAME_TTL = 24 * 3600 * 1000;

class Runner {
    /**
     * api: API zca-js đã đăng nhập; store: Store; status: object trạng thái dùng chung với vòng gửi Odoo;
     * relogin: hàm (async) đăng nhập lại rồi tạo Runner mới — gọi khi rớt liên tiếp quá nhiều.
     */
    constructor({ api, store, status, config, log, relogin }) {
        Object.assign(this, { api, store, status, config, log, relogin });
        this.failures = 0;
        this.stableTimer = null;
        this.retryTimer = null;
        this.stopped = false;
    }

    start() {
        const listener = this.api.listener;
        listener.on("connected", () => this._onConnected());
        listener.on("closed", (code, reason) => this._onClosed(code, reason));
        listener.on("error", (error) => this.log.warn("Lỗi kết nối nghe:", (error && error.message) || String(error)));
        listener.on("message", (message) => this._saveMessage(message));
        listener.on("old_messages", (messages, type) => {
            if (type === ThreadType.Group) {
                messages.forEach((message) => this._saveMessage(message));
                this.log.info(`Lấy bù: nhận ${messages.length} tin nhóm`);
            }
        });
        listener.on("reaction", (reaction) => this._saveReaction(reaction));
        this._connect();
    }

    stop() {
        this.stopped = true;
        clearTimeout(this.stableTimer);
        clearTimeout(this.retryTimer);
        this.api.listener.removeAllListeners();
        this.api.listener.stop();
    }

    _connect() {
        this.status.state = "reconnecting";
        this.api.listener.start({ retryOnClose: false });
    }

    _onConnected() {
        this.status.state = "connected";
        this.status.connected_since = Date.now();
        this.log.info("Listener đã kết nối");
        clearTimeout(this.stableTimer);
        this.stableTimer = setTimeout(() => {
            this.failures = 0;
        }, STABLE_MS);
        if (fs.existsSync(this.config.noBackfillFlag)) {
            return;
        }
        try {
            this.api.listener.requestOldMessages(ThreadType.Group, null);
        } catch (error) {
            this.log.warn("Không xin được tin cũ:", error.message);
        }
    }

    _onClosed(code, reason) {
        clearTimeout(this.stableTimer);
        if (this.stopped) {
            return;
        }
        this.status.last_close_code = code;
        this.status.last_close_at = Date.now();
        this.status.drops_today += 1;
        const plan = onClose(code, this.failures);
        this.log.warn(`Rớt kết nối: mã ${code} ${reason || ""} → ${plan.action} sau ${Math.round(plan.wait / 1000)} giây (${plan.reason})`);
        if (plan.action === "stop") {
            this.status.state = code === 1000 ? "stopped" : "kicked";
            this.status.last_error = plan.reason;
            return;
        }
        this.failures += 1;
        this.status.state = "reconnecting";
        this.retryTimer = setTimeout(() => {
            if (plan.action === "relogin") {
                this.stop();
                this.relogin();
            } else {
                this._connect();
            }
        }, plan.wait);
    }

    async _groupName(groupId) {
        const cached = this.store.groupName(groupId);
        if (cached && Date.now() - cached.updated_at < GROUP_NAME_TTL) {
            return cached.name;
        }
        try {
            const info = await this.api.getGroupInfo(groupId);
            const name = ((info.gridInfoMap || {})[groupId] || {}).name || "";
            if (name) {
                this.store.saveGroupName(groupId, name);
            }
            return name || (cached && cached.name) || "";
        } catch (error) {
            // Tin vẫn ghi, tên nhóm để trống — Odoo điền bù khi tin sau có tên.
            this.log.warn(`Không tra được tên nhóm ${groupId}:`, error.message);
            return (cached && cached.name) || "";
        }
    }

    // Một tin lỗi không được làm sập cả chương trình: bọc từng tin.
    async _saveMessage(message) {
        try {
            if (message.type !== ThreadType.Group) {
                return; // tin 1-1 gửi tài khoản nghe: không lưu
            }
            const payload = normalizeMessage(message, await this._groupName(String(message.threadId)));
            if (payload) {
                this.store.saveMessage(payload);
            }
        } catch (error) {
            this.log.error("Lỗi ghi tin (đã bỏ qua tin này):", error.message);
        }
    }

    _saveReaction(reaction) {
        try {
            const payload = normalizeReaction(reaction);
            if (payload) {
                this.store.saveReaction(reactionKey(payload), payload);
            }
        } catch (error) {
            this.log.error("Lỗi ghi thả cảm xúc (đã bỏ qua):", error.message);
        }
    }
}

module.exports = { Runner };
