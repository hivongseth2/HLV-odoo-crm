/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PartnerLine } from "@point_of_sale/app/screens/partner_list/partner_line/partner_line";
import { useService } from "@web/core/utils/hooks";

patch(PartnerLine.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        // No need for pos service if we don't reload
    },

    async onToggleCustomerType(ev) {
        ev.stopPropagation(); // Avoid selecting the partner row

        const partner = this.props.partner;
        const currentType = partner.pos_customer_type;

        let newType = false;
        if (currentType === 'cash') {
            newType = 'bank';
        } else if (currentType === 'bank') {
            newType = false; // Toggle to empty
        } else {
            newType = 'cash';
        }

        try {
            // Optimistic UI Update: Update local model immediately
            // Since Odoo 18 uses reactive record objects in POS, this might trigger UI update
            // However, verify if 'partner' is directly mutable or if we need to go through DB
            const oldType = partner.pos_customer_type;
            partner.pos_customer_type = newType;

            // Update backend
            await this.orm.write("res.partner", [partner.id], {
                pos_customer_type: newType
            });

            console.log(`[HLV] Toggled partner ${partner.name} (${partner.id}) type to ${newType}`);

        } catch (error) {
            console.error("[HLV] Failed to update customer type:", error);
            // Revert on error
            // partner.pos_customer_type = oldType; // Need to keep oldType in scope if revert needed
            // Ensure UI shows error state if needed
        }
    }
});
