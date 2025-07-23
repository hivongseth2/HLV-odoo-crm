/** @odoo-module **/

import { registry } from "@web/core/registry";
const { patch } = require("@web/core/utils/patch");
const { PickingClientAction } = require("@stock_barcode/components/picking_client_action/picking_client_action");

patch(PickingClientAction.prototype, {
    setup() {
        this._super();
        if (!this.env.config.isDebug) {
            this.env.bus.addEventListener("ACTION_REDIRECT_TO_PACK", this.onRedirectToPack.bind(this));
        }
    },

    async onRedirectToPack() {
        const result = await this.rpc("/stock_pick_to_pack_button/redirect", {
            picking_id: this.props.picking.id,
        });

        if (result && result.action) {
            this.env.services.action.doAction(result.action);
        } else {
            this.env.services.notification.add(result.warning || "Không tìm thấy phiếu pack");
        }
    },

    get additionalButtons() {
        return [
            ...this._super(),
            {
                text: "Go to Pack",
                type: "button",
                className: "btn btn-primary",
                onClick: () => this.onRedirectToPack(),
                icon: "fa fa-arrow-right",
            },
        ];
    },
});
