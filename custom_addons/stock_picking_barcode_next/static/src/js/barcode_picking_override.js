
import { registry } from "@web/core/registry";
import { PickingClientAction } from "@stock_barcode/components/picking_client_action/picking_client_action";
import { patch } from "@web/core/utils/patch";

patch(PickingClientAction.prototype, {
    async onValidate() {
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
