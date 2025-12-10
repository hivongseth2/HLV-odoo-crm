/** @odoo-module */

import { actionService } from "@web/webclient/actions/action_service";
import { patch } from "@web/core/utils/patch";
import { browser } from "@web/core/browser/browser";

// LƯU Ý: Patch trực tiếp vào actionService (không có .prototype)
patch(actionService, {
    start(env) {
        // 1. Gọi hàm start gốc để lấy về instance của service (chứa các hàm doAction, restore...)
        const service = super.start(env);

        // 2. Định nghĩa hàm xử lý sự kiện Back
        const onPopState = async (ev) => {
            // Chúng ta gọi hàm restore() của Odoo.
            // Hàm này sẽ lấy controller trước đó trong ngăn xếp (stack) bộ nhớ ra hiển thị.
            // Nó giữ lại filter, scroll, v.v.
            try {
                // service.restore() là promise, trả về controllerID nếu thành công
                await service.restore();
            } catch (error) {
                // Nếu không restore được (ví dụ đang ở trang chủ, hết stack), thì kệ nó
                console.debug("Custom Back Button: Cannot restore state", error);
            }
        };

        // 3. Gắn sự kiện lắng nghe nút Back của trình duyệt
        browser.addEventListener("popstate", onPopState);

        // 4. Trả về service instance để hệ thống sử dụng
        return service;
    }
});