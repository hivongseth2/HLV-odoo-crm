
odoo.define('stock_picking_barcode_next_group.barcode_override', function (require) {
    'use strict';

    const { PickingClientAction } = require('@stock_barcode/components/picking_client_action/picking_client_action');
    const patchMixin = require('web.patchMixin');
    const { patch } = require('web.utils');

    patch(PickingClientAction.prototype, {
        async onValidate() {
            console.log("[PATCHED] onValidate override is running ✅");
            const result = await this.model.validate();
            if (result?.commands?.[0]?.type === "ir.actions.client" && this.model.picking.state === "done") {
                const groupId = this.model.picking.group_id?.[0];
                const currentId = this.model.picking.id;

                if (groupId) {
                    try {
                        const response = await this.orm.call(
                            "stock.picking",
                            "get_next_picking_by_group",
                            [currentId],
                            { context: { group_id: groupId } }
                        );

                        if (response && response.next_picking_id) {
                            console.log("🔁 Đang mở phiếu tiếp theo:", response.next_picking_id);
                            await this.action.doAction("stock_barcode.stock_barcode_picking_client_action", {
                                additional_context: {
                                    active_id: response.next_picking_id,
                                    active_ids: [response.next_picking_id],
                                    active_model: "stock.picking",
                                },
                            });
                            return;
                        }
                    } catch (error) {
                        console.warn("Không tìm được phiếu kế tiếp:", error);
                    }
                }
            }
            this.actionService.doAction(result.commands[0]);
        },
    });
});
