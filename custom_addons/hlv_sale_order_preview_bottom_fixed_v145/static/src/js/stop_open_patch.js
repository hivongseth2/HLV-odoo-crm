/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";

/**
 * Chặn hành vi mở form khi bấm nút "Xem nhanh (HLV)" trong hàng list.
 * Bắt ở capture phase để ngăn List xử lý click vào row.
 */

// Lưu reference tới method gốc
const _setup = ListRenderer.prototype.setup;
const _mounted = ListRenderer.prototype.mounted;
const _willUnmount = ListRenderer.prototype.willUnmount;

patch(ListRenderer.prototype, {
    setup() {
        // GỌI LẠI HÀM GỐC
        if (_setup) {
            _setup.call(this, ...arguments);
        }
        // Handler chặn click
        this._hlvOnClickCapture = (ev) => {
            const btn = ev.target?.closest?.(".hlv-quick-btn");
            if (btn) {
                ev.stopPropagation();
                ev.preventDefault();
            }
        };
    },

    mounted() {
        // GỌI LẠI HÀM GỐC
        if (_mounted) {
            _mounted.call(this, ...arguments);
        }
        // Bắt sớm ở capture phase để chặn row-click
        this.el.addEventListener("click", this._hlvOnClickCapture, { capture: true });
    },

    willUnmount() {
        // GỠ LISTENER + GỌI LẠI HÀM GỐC
        try {
            this.el?.removeEventListener("click", this._hlvOnClickCapture, { capture: true });
        } finally {
            if (_willUnmount) {
                _willUnmount.call(this, ...arguments);
            }
        }
    },
});
