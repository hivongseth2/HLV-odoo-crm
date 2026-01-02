/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PartnerList } from "@point_of_sale/app/screens/partner_list/partner_list";
import { onMounted } from "@odoo/owl";

console.log("[HLV DEBUG] Module hlv_pos_customer_type JS loaded.");

patch(PartnerList.prototype, {
    setup() {
        super.setup();
        onMounted(() => {
            console.log("[HLV DEBUG] PartnerList Mounted.");
            const samplePartner = this.getPartners()[0];
            if (samplePartner) {
                console.log("[HLV DEBUG] Sample Partner Data:", samplePartner);
                console.log("[HLV DEBUG] pos_customer_type value:", samplePartner.pos_customer_type);
            } else {
                console.log("[HLV DEBUG] No partners found via getPartners()");
            }
        });
    }
});
