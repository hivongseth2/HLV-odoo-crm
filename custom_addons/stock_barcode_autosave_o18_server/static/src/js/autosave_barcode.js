
/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { PickingClientAction } from "@stock_barcode/picking_client_action/picking_client_action";
import { PickingLine } from "@stock_barcode/picking_client_action/models/picking_line";

function orm(model, method, args=[], kwargs={}) {
    return rpc("/web/dataset/call_kw", { model, method, args, kwargs });
}

let t;
const debounce = (fn, ms=350) => { clearTimeout(t); t = setTimeout(fn, ms); };

// After scan: persist any in-memory lines lacking an id by calling server helper.
patch(PickingClientAction.prototype, "autosave-server-after-scan", {
    async onBarcodeScanned(code) {
        await this._super(code);
        const picking = this.model?.picking;
        if (!picking?.id) return;

        debounce(async () => {
            try {
                // Collect lines that have qty_done > 0 but have no server id yet
                const pending = [];
                for (const line of this.model?.lines || []) {
                    if (!line?.data) continue;
                    const hasId = !!line.data.id;
                    const qty = Number(line.qty_done || line.data.qty_done || 0);
                    if (hasId || !qty) continue;

                    // Try to extract product/move/uom/locations best-effort from client model
                    const productId = line.data.product?.id || line.data.product_id;
                    const moveId = line.data.move?.id || line.data.move_id;
                    const uomId = line.data.product_uom?.id || line.data.product_uom_id;
                    const locId = line.data.location?.id || line.data.location_id || (picking.location_id && picking.location_id[0]);
                    const locDestId = line.data.location_dest?.id || line.data.location_dest_id || (picking.location_dest_id && picking.location_dest_id[0]);
                    const lotId = line.data.lot?.id || line.data.lot_id;

                    pending.push({
                        client_key: String(line.__owl__?.id || line.id || Math.random()),
                        product_id: productId,
                        move_id: moveId,
                        uom_id: uomId,
                        location_id: locId,
                        location_dest_id: locDestId,
                        lot_id: lotId,
                        qty_done: qty,
                    });
                }

                if (pending.length) {
                    const res = await orm("stock.picking", "barcode_autosave_create_lines", [pending], {context: this.model?.context || {}});
                    // Assign returned ids back to client lines to align future +/- writes
                    const map = Object.fromEntries(res.map(r => [String(r.client_key), r.line_id]));
                    for (const line of this.model?.lines || []) {
                        const key = String(line.__owl__?.id || line.id || "");
                        if (map[key] && !line.data.id) {
                            line.data.id = map[key];
                        }
                    }
                }
            } catch (e) {
                console.warn("[Autosave] server-assisted create failed", e);
            }
        }, 250);
    },

    setup() {
        this._super();
        console.log("%c[Barcode Autosave] server-assisted loaded (Odoo 18)",
            "padding:2px 6px;border-radius:6px;background:#222;color:#9fe870");
    },
});

// When qty changes on an existing server line, persist immediately.
patch(PickingLine.prototype, "autosave-server-qty", {
    async setQtyDone(newQty) {
        await this._super(newQty);
        const id = this.data && this.data.id;
        if (!id) return;
        try {
            await orm("stock.move.line", "write", [[id], { qty_done: this.qty_done }], {});
        } catch (e) {
            console.warn("[Autosave] write qty_done failed", e);
        }
    },
});
