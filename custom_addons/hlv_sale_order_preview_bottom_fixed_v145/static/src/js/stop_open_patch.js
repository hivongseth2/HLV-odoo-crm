/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";

/**
 * Ngăn list mở form khi bấm nút "Xem nhanh (HLV)" trong hàng.
 * Bắt sự kiện click ở capture phase để chặn sớm trước khi List xử lý.
 */
patch(ListRenderer.prototype, "hlv/stop-open-on-quick-button", {
    setup() {
        // gọi setup gốc (nếu có)
        if (super.setup) {
            super.setup();
        }
        this._hlvOnClickCapture = (ev) => {
            // Nếu click lên chính nút "Xem nhanh (HLV)" hoặc con của nó -> chặn
            const btn = ev.target.closest(".hlv-quick-btn");
            if (btn) {
                ev.stopPropagation();
                // Đề phòng: một số browser cần preventDefault để không trigger focus/row handlers
                ev.preventDefault();
            }
        };
    },
    mounted() {
        if (super.mounted) {
            super.mounted();
        }
        // Bắt ở capture phase để chặn sớm
        this.el.addEventListener("click", this._hlvOnClickCapture, { capture: true });
    },
    willUnmount() {
        this.el.removeEventListener("click", this._hlvOnClickCapture, { capture: true });
        if (super.willUnmount) {
            super.willUnmount();
        }
    },
});
