/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { Breadcrumbs } from "@web/webclient/breadcrumbs/breadcrumbs";

/**
 * HLV Browser Back Button
 * 
 * Thay đổi hành vi của nút back (breadcrumb đầu tiên) trong Odoo:
 * - Sử dụng history.back() của trình duyệt thay vì restore action mặc định
 * - Đưa người dùng về đúng trang trước đó trong lịch sử duyệt web
 * - Giữ nguyên các bộ lọc và trạng thái tìm kiếm
 */

patch(Breadcrumbs.prototype, {
    /**
     * Override onBreadcrumbClicked để sử dụng history.back()
     * cho breadcrumb đầu tiên (nút back chính hiển thị tên ứng dụng)
     * 
     * @param {Event} ev - Click event
     * @param {Number} index - Index của breadcrumb được click
     */
    onBreadcrumbClicked(ev, index) {
        // Kiểm tra nếu click vào breadcrumb đầu tiên (index = 0)
        // và có nhiều hơn 1 breadcrumb (đang ở trong một record/view)
        const breadcrumbs = this.props.breadcrumbs || [];

        if (index === 0 && breadcrumbs.length > 1) {
            ev.preventDefault();
            ev.stopPropagation();

            // Sử dụng history.back() để quay lại trang trước đó
            // Điều này giữ nguyên các bộ lọc và trạng thái tìm kiếm
            window.history.back();
            return;
        }

        // Với các breadcrumb khác (không phải đầu tiên), 
        // sử dụng hành vi mặc định của Odoo
        if (super.onBreadcrumbClicked) {
            super.onBreadcrumbClicked(ev, index);
        }
    }
});

console.log("[HLV] Browser Back Button module loaded - Back button now uses browser history");
