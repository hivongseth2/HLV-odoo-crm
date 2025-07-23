/** @odoo-module **/
import { registry } from "@web/core/registry";
import { PickingBarcodeHandler } from "@stock_barcode/js/picking_barcode_handler";
import { patch } from "@web/core/utils/patch";

patch(PickingBarcodeHandler.prototype, {
    async _loadData(pickingId) {
        const res = await super._loadData(pickingId);

        if (this.pickingData.state === 'done') {
            const relatedPack = await this.rpc("/barcode_pick_to_pack/find_pack", {
                origin: this.pickingData.name
            });

            if (relatedPack && relatedPack.id) {
                // Redirect to the pack
                this.env.services.action.doAction({
                    type: "ir.actions.client",
                    tag: "barcode_picking_client_action",
                    params: {
                        barcode_picking_id: relatedPack.id
                    }
                });
            } else {
                this.notification.add("Không tìm thấy phiếu pack liên quan chưa done.", {
                    type: "warning",
                });
            }
        }

        return res;
    }
});
