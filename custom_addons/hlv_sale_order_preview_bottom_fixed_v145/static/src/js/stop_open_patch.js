/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { ListController } from "@web/views/list/list_controller";

/**
 * Mục tiêu:
 * - Khi bấm nút .hlv-quick-btn trong hàng list, KHÔNG được mở form detail.
 * - Chặn ở cả Renderer (capture phase) và Controller (openRecord/onRowClicked).
 */

/* --- 1) Patch ListRenderer: chặn click sớm ở capture phase --- */
const _lr_setup = ListRenderer.prototype.setup;
const _lr_mounted = ListRenderer.prototype.mounted;
const _lr_willUnmount = ListRenderer.prototype.willUnmount;

patch(ListRenderer.prototype, {
    setup() {
        if (_lr_setup) _lr_setup.call(this, ...arguments);
        this._hlvOnClickCapture = (ev) => {
            const btn = ev.target?.closest?.(".hlv-quick-btn");
            if (btn) {
                ev.stopPropagation();
                ev.preventDefault();
            }
        };
    },
    mounted() {
        if (_lr_mounted) _lr_mounted.call(this, ...arguments);
        this.el.addEventListener("click", this._hlvOnClickCapture, { capture: true });
    },
    willUnmount() {
        try {
            this.el?.removeEventListener("click", this._hlvOnClickCapture, { capture: true });
        } finally {
            if (_lr_willUnmount) _lr_willUnmount.call(this, ...arguments);
        }
    },
});

/* --- 2) Patch ListController: chặn mở record nếu click từ .hlv-quick-btn --- */
const _lc_openRecord = ListController.prototype.openRecord;
const _lc_onRowClicked = ListController.prototype.onRowClicked;

patch(ListController.prototype, {
    async openRecord(record, options = {}) {
        const ev = options?.event;
        if (ev && ev.target && ev.target.closest && ev.target.closest(".hlv-quick-btn")) {
            // người dùng click nút xem nhanh -> tuyệt đối không mở form
            ev.stopPropagation?.();
            ev.preventDefault?.();
            return; // dứt điểm ở đây
        }
        return _lc_openRecord.call(this, record, options);
    },

    async onRowClicked(ev) {
        if (ev && ev.target && ev.target.closest && ev.target.closest(".hlv-quick-btn")) {
            ev.stopPropagation?.();
            ev.preventDefault?.();
            return;
        }
        return _lc_onRowClicked.call(this, ev);
    },
});
