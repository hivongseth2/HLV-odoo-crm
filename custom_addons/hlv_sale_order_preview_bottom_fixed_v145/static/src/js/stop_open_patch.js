/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";

/**
 * Chặn hành vi mở form khi bấm nút "Xem nhanh (HLV)" trong hàng list.
 * Bắt ở capture phase để ngăn List xử lý click vào row.
 */
patch(ListRenderer.prototype, {
    setup() {
        // gọi setup gốc nếu có
        if (this._super) {
            this._super(...arguments);
        }
        this._hlvOnClickCapture = (ev) => {
            const btn = ev.target && ev.target.closest && ev.target.closest(".hlv-quick-btn");
            if (btn) {
                ev.stopPropagation();
                ev.preventDefault();
            }
        };
    },

    mounted() {
        if (this._super) {
            this._super(...arguments);
        }
        // Bắt sớm ở capture phase
        this.el.addEventListener("click", this._hlvOnClickCapture, { capture: true });
    },

    willUnmount() {
        // Gỡ listener trước khi unmount
        if (this.el && this._hlvOnClickCapture) {
            this.el.removeEventListener("click", this._hlvOnClickCapture, { capture: true });
        }
        if (this._super) {
            this._super(...arguments);
        }
    },
});
