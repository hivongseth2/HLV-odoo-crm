/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";

const _openRecord = ListController.prototype.openRecord;
const _onRowClicked = ListController.prototype.onRowClicked;

patch(ListController.prototype, {
    async openRecord(record, options = {}) {
        const ev = options?.event;
        if (ev && ev.target?.closest(".hlv-quick-btn")) {
            // Click từ nút HLV → không mở record
            ev.stopPropagation?.();
            ev.preventDefault?.();
            return;
        }
        return _openRecord.call(this, record, options);
    },

    async onRowClicked(ev) {
        if (ev && ev.target?.closest(".hlv-quick-btn")) {
            ev.stopPropagation?.();
            ev.preventDefault?.();
            return;
        }
        return _onRowClicked.call(this, ev);
    },
});
