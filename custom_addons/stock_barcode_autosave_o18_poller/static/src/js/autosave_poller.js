
/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { PickingClientAction } from "@stock_barcode/picking_client_action/picking_client_action";
import { PickingLine } from "@stock_barcode/picking_client_action/models/picking_line";

function orm(model, method, args=[], kwargs={}) {
    return rpc("/web/dataset/call_kw", { model, method, args, kwargs });
}

async function persistPending(model) {
    const picking = model?.picking;
    if (!picking?.id) return;
    const pending = [];
    for (const line of model?.lines || []) {
        if (!line?.data) continue;
        const hasId = !!line.data.id;
        const qty = Number(line.qty_done || line.data.qty_done || 0);
        if (hasId || !qty) continue;

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
        const res = await orm("stock.picking", "barcode_autosave_create_lines", [pending], {context: model?.context || {}});
        const map = Object.fromEntries(res.map(r => [String(r.client_key), r.line_id]));
        for (const line of model?.lines || []) {
            const key = String(line.__owl__?.id || line.id || "");
            if (map[key] && !line.data.id) {
                line.data.id = map[key];
            }
        }
    }
}

let intervalId = null;

patch(PickingClientAction.prototype, "autosave-poller-o18", {
    setup() {
        this._super();
        console.log("%c[Barcode Autosave] poller loaded (Odoo 18)",
            "padding:2px 6px;border-radius:6px;background:#222;color:#9fe870");
        // Poll every 700ms to persist client-only lines to server
        intervalId = setInterval(() => {
            persistPending(this.model).catch(e => console.warn("[Autosave] poll persist failed", e));
        }, 700);
    },
    onWillUnmount() {
        this._super();
        if (intervalId) clearInterval(intervalId);
        intervalId = null;
    },
});

// Also persist +/- changes immediately for lines that already have an id
patch(PickingLine.prototype, "autosave-poller-qty", {
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
