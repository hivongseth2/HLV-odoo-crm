/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

// Websocket là đường chính; hỏi lại định kỳ để trang vẫn tự chuyển khi proxy chặn websocket.
const FALLBACK_POLL_MS = 15000;
const BUS_NOTIFICATION = "hlv_login_approval/update";

publicWidget.registry.HlvLoginApprovalWait = publicWidget.Widget.extend({
    selector: ".o_hlv_login_wait",

    start() {
        const { channel, statusUrl, continueUrl } = this.el.dataset;
        this.statusUrl = statusUrl;
        this.continueUrl = continueUrl;
        // Yêu cầu tạo trước bản có bus thì không có kênh: chỉ còn hỏi định kỳ.
        try {
            if (!channel) {
                throw new Error("no bus channel");
            }
            const busService = this.bindService("bus_service");
            busService.subscribe(BUS_NOTIFICATION, ({ state }) => this._applyState(state));
            busService.addChannel(channel);
        } catch {
            // Không có bus thì vẫn còn hỏi định kỳ bên dưới.
        }
        this.pollTimer = setInterval(() => this._checkStatus(), FALLBACK_POLL_MS);
        return this._super(...arguments);
    },

    destroy() {
        clearInterval(this.pollTimer);
        this._super(...arguments);
    },

    async _checkStatus() {
        try {
            const response = await fetch(this.statusUrl, { credentials: "same-origin" });
            if (response.ok) {
                this._applyState((await response.json()).state);
            }
        } catch {
            // Mất mạng tạm thời: lần hỏi sau thử lại.
        }
    },

    _applyState(state) {
        if (state === "approved") {
            window.location.assign(this.continueUrl);
        } else if (state === "rejected" || state === "expired" || state === "none") {
            // Tải lại để server hiện trang bị từ chối / hết hạn / đưa về trang đăng nhập.
            clearInterval(this.pollTimer);
            window.location.reload();
        }
    },
});
