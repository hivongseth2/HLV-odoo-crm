
odoo.define('stock_picking_barcode_next_group.override', function (require) {
    "use strict";

    const PickingClientAction = require('stock_barcode.PickingClientAction');
    const rpc = require('web.rpc');
    const core = require('web.core');

    const _t = core._t;

    PickingClientAction.include({
        async onValidate() {
            await this._super.apply(this, arguments);

            const pickingId = this.actionParams?.context?.active_id;
            if (!pickingId) return;

            console.log("✅ Phiếu hiện tại:", pickingId);

            try {
                const nextId = await rpc.query({
                    route: "/stock_barcode/get_next_picking_by_group",
                    params: { picking_id: pickingId },
                });

                if (nextId) {
                    console.log("➡️ Mở phiếu kế tiếp:", nextId);
                    this.do_action("stock_barcode.stock_barcode_picking_client_action", {
                        additional_context: {
                            active_id: nextId,
                            active_ids: [nextId],
                            active_model: "stock.picking",
                        },
                    });
                } else {
                    console.log("✅ Không còn phiếu nào trong nhóm.");
                }
            } catch (e) {
                console.error("❌ Lỗi khi tìm phiếu kế tiếp:", e);
            }
        }
    });
});
