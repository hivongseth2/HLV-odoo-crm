/** @odoo-module */

import { ActionService } from "@web/webclient/actions/action_service";
import { patch } from "@web/core/utils/patch";
import { browser } from "@web/core/browser/browser";

patch(ActionService.prototype, {
    setup() {
        super.setup();
        // Gắn sự kiện lắng nghe nút Back của trình duyệt
        this._onPopStateBound = this._onBrowserBack.bind(this);
        browser.addEventListener("popstate", this._onPopStateBound);
    },

    /**
     * Hàm xử lý khi bấm Back trình duyệt
     */
    async _onBrowserBack(ev) {
        // Kiểm tra xem trong stack của Odoo có trang trước đó không
        // this.controllerStack chứa lịch sử nội bộ (Breadcrumbs)
        if (this.controllerStack && this.controllerStack.length > 1) {

            // QUAN TRỌNG: Ngăn chặn router mặc định của Odoo xử lý URL
            // (Lưu ý: Chúng ta không thể ngăn URL thay đổi vì popstate xảy ra sau khi URL đổi,
            // nhưng ta có thể can thiệp vào hành vi load lại view)

            // Gọi hàm restore() của Odoo để quay lại view trước đó từ bộ nhớ
            // Hành động này tương đương với việc bấm vào Breadcrumbs
            await this.restore();

            // Tùy chọn: Đẩy lại URL cũ vào history nếu muốn URL khớp với View
            // (Phần này hơi tricky vì có thể gây loop, bạn nên test kỹ)
        }
    },
});