/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PickingClientAction } from "@stock_barcode/picking_client_action/picking_client_action";
import { PickingLine } from "@stock_barcode/picking_client_action/models/picking_line";
import { rpc } from "@web/core/network/rpc_service";

let saveTimer;
const debounce = (fn, ms = 300) => {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(fn, ms);
};

patch(PickingClientAction.prototype, "autosave-after-scan-o18", {
    async onBarcodeScanned(code) {
        await this._super(code);
        debounce(async () => {
            try {
                if (this.model?.save) {
                    await this.model.save();
                }
            } catch (e) {
                console.warn("[Barcode Autosave] save() failed:", e);
            }
        }, 250);
    },

    setup() {
        this._super();
        window.addEventListener("beforeunload", () => {
            if (this.model?.save) {
                try { this.model.save(); } catch (_) {}
            }
        });
    },
});

patch(PickingLine.prototype, "autosave-qty-done-o18", {
    async setQtyDone(newQty) {
        await this._super(newQty);
        const lineId = this.data?.id;
        if (!lineId) return;
        try {
            await rpc("/web/dataset/call_kw", {
                model: "stock.move.line",
                method: "write",
                args: [[lineId], { qty_done: this.qty_done }],
                kwargs: {},
            });
        } catch (e) {
            console.warn("[Barcode Autosave] write qty_done failed:", e);
        }
    },
});
