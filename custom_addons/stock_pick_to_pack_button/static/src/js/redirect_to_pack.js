/** @odoo-module **/

import { registry } from "@web/core/registry";
import { BarcodeMainComponent } from "@stock_barcode/components/barcode_main";

const patchBarcode = {
    async setup() {
        await this._super(...arguments);
        if (this.env.services.action.current?.res_model === 'stock.picking') {
            const picking = this.env.services.action.current?.context?.barcode_picking_data;
            if (picking?.state === 'done' && picking?.origin) {
                const pack = await this.orm.searchRead('stock.picking', [
                    ['origin', '=', picking.name],
                    ['state', 'not in', ['done', 'cancel']],
                    ['picking_type_id.code', '=', 'outgoing'],
                ], ['id'], { limit: 1 });

                if (pack.length) {
                    this.env.services.action.doAction({
                        type: 'ir.actions.client',
                        tag: 'barcode_picking_client_action',
                        params: { barcode_picking_id: pack[0].id },
                    });
                }
            }
        }
    }
};

registry.category("actions").add("barcode_picking_client_action", {
    ...BarcodeMainComponent,
    ...patchBarcode,
});
