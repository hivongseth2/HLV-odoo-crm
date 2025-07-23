/** @odoo-module **/

import { PickingClientAction } from "@stock_barcode/js/picking_client_action";
import { patch } from "@web/core/utils/patch";

patch(PickingClientAction.prototype, {
    async setup() {
        await this._super(...arguments);

        if (this.picking?.state === 'done') {
            const packId = await this.rpc("/stock/barcode/redirect_to_pack", {
                origin: this.picking.name,
            });

            if (packId) {
                this.env.services.action.doAction({
                    type: 'ir.actions.client',
                    tag: 'barcode_picking_client_action',
                    params: {
                        barcode_picking_id: packId,
                    },
                });
            }
        }
    }
});