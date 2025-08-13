
/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { PickingClientAction } from "@stock_barcode/picking_client_action/picking_client_action";
import { PickingLine } from "@stock_barcode/picking_client_action/models/picking_line";

// Small helper to call ORM write
function write(model, ids, vals) {
    return rpc("/web/dataset/call_kw", {
        model, method: "write", args: [ids, vals], kwargs: {},
    });
}

let t;
const debounce = (fn, ms = 400) => { clearTimeout(t); t = setTimeout(fn, ms); };

// --- PATCH 1: After every scan, attempt to persist changes ---
patch(PickingClientAction.prototype, "autosave-after-scan-o18-fix", {
    async onBarcodeScanned(code) {
        await this._super(code);
        // Try to persist model state after scan. Some builds expose model.save().
        debounce(async () => {
            try {
                if (this.model && this.model.save) {
                    await this.model.save();
                    // console.log("[Autosave] save() ok");
                }
            } catch (e) {
                console.warn("[Autosave] model.save() failed", e);
            }
        }, 250);
    },

    setup() {
        this._super();
        // Visual hint in console to confirm patch is loaded
        console.log("%c[Barcode Autosave] loaded for Odoo 18",
            "padding:2px 6px;border-radius:6px;background:#222;color:#9fe870");
        // Best effort: save when leaving page
        window.addEventListener("beforeunload", () => {
            if (this.model && this.model.save) {
                try { this.model.save(); } catch (_) { }
            }
        });
    },
});

// --- PATCH 2: Persist a line immediately when qty_done changes ---
patch(PickingLine.prototype, "autosave-qty-done-o18-fix", {
    async setQtyDone(newQty) {
        await this._super(newQty);
        const id = this.data && this.data.id;
        // Only existing move lines have an id. New lines created by scan will be
        // persisted by PATCH 1's save(); after that, further +/- will hit here.
        if (!id) return;
        try {
            await write("stock.move.line", [id], { qty_done: this.qty_done });
            // console.log("[Autosave] line written", id, this.qty_done);
        } catch (e) {
            console.warn("[Autosave] write qty_done failed", e);
        }
    },
});
