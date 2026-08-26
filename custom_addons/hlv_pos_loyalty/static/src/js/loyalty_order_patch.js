/** @odoo-module */
import { Order } from "@point_of_sale/app/store/models";
import { patch } from "@web/core/utils/patch";

patch(Order.prototype, {
    setup() {
        super.setup(...arguments);
        this.loyalty_account_id = this.loyalty_account_id || null;
        this.loyalty_account = this.loyalty_account || null;
    },

    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);
        json.loyalty_account_id = this.loyalty_account_id;
        return json;
    },

    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        this.loyalty_account_id = json.loyalty_account_id;
    },
});
