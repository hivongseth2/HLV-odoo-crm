/** @odoo-module **/

import { registry } from "@web/core/registry";

registry.category("barcode_handlers").add("redirect_to_pack_if_pick_done", {
    async onBarcodeScanned({ env, barcode }) {
        const result = await env.services.orm.call("stock.picking", "search_read", [
            [["name", "=", barcode]],
            ["id", "name", "origin", "state", "picking_type_id"]
        ]);

        const picking = result[0];
        if (picking?.state === 'done') {
            const pack = await env.services.orm.call("stock.picking", "search_read", [
                [["origin", "=", picking.name], ["state", "!=", "done"]],
                ["id"]
            ], { limit: 1 });

            if (pack.length) {
                env.services.action.doAction({
                    type: "ir.actions.client",
                    tag: "barcode_picking_client_action",
                    params: { barcode_picking_id: pack[0].id },
                });
            }
        }
    }
});
