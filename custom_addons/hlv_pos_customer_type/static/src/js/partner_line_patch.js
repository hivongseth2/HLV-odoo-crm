/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PartnerLine } from "@point_of_sale/app/screens/partner_list/partner_line/partner_line";
import { useService } from "@web/core/utils/hooks";

patch(PartnerLine.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.pos = useService("pos");
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
            // Updated backend
            await this.orm.write("res.partner", [partner.id], {
                pos_customer_type: newType
            });

            // Reload partner data in POS to reflect changes
            await this.pos.load_new_partners();

            console.log(`[HLV] Toggled partner ${partner.name} (${partner.id}) type to ${newType}`);

        } catch (error) {
            console.error("[HLV] Failed to update customer type:", error);
            // Optionally show an error popup
        }
    }
});
