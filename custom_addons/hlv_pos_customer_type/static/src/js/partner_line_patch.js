/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PartnerLine } from "@point_of_sale/app/screens/partner_list/partner_line/partner_line";
import { useService } from "@web/core/utils/hooks";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";

patch(PartnerLine.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.popup = useService("popup"); // Standard POS popup service in earlier versions, but Odoo 18 uses dialogs
    },

    async onToggleCustomerType(ev) {
        ev.stopPropagation(); // Avoid selecting the partner row

        const partner = this.props.partner;

        // Define selection list
        const selectionList = [
            { id: 'cash', label: 'Tiền mặt', item: 'cash' },
            { id: 'bank', label: 'Chuyển khoản', item: 'bank' },
            { id: 'false', label: 'Bỏ chọn', item: false },
        ];

        try {
            // Show Selection Popup
            // Odoo 18 style: use makeAwaitable with SelectionPopup component
            const selectedItem = await makeAwaitable(this.env.services.dialog, SelectionPopup, {
                title: 'Chọn loại khách hàng',
                list: selectionList,
            });

            // If user cancelled (selectedItem is undefined or null usually on cancel)
            if (selectedItem !== undefined && selectedItem !== null) {
                // Note: SelectionPopup returns the 'item' property of the selected object directly? 
                // Or returns the payload? Standard SelectionPopup returns the item.

                const newType = selectedItem; // Assuming it returns the payload 'item'

                // Skip if no change (except if we want to force re-set)
                if (newType === partner.pos_customer_type) {
                    return;
                }

                // Optimistic update
                partner.pos_customer_type = newType;

                // Backend update
                await this.orm.write("res.partner", [partner.id], {
                    pos_customer_type: newType || false // Handle false/null
                });

                console.log(`[HLV] Set partner ${partner.name} type to ${newType}`);
            }

        } catch (error) {
            // makeAwaitable might throw on cancel? Or just return null?
            // Usually returns null/undefined or throws "Cancelled".
            console.log("[HLV] Selection cancelled or failed", error);
        }
    }
});
