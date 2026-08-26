/** @odoo-module */
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    setup(vals) {
        super.setup(vals);
        // These fields are custom POS-only state.  They must exist before the
        // order becomes reactive and must be restored when an offline order is
        // loaded back from IndexedDB.
        this.loyalty_account_id = vals.loyalty_account_id || null;
        this.loyalty_account = vals.loyalty_account || null;
    },

    serialize() {
        const data = super.serialize(...arguments);
        // Odoo 18 sends POS orders through serialize({ orm: true }), replacing
        // the legacy export_as_JSON() flow.
        data.loyalty_account_id = this.loyalty_account_id || false;
        return data;
    },
});
