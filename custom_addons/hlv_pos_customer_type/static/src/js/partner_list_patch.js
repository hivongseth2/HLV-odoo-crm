/** @odoo-module */

import { PartnerListScreen } from "@point_of_sale/app/screens/partner_list/partner_list";
import { patch } from "@web/core/utils/patch";

patch(PartnerListScreen.prototype, {
    get partners() {
        const partners = super.partners;
        if (!partners) {
            return [];
        }
        // Filter out child contacts (only show parents)
        return partners.filter(partner => !partner.parent_id);
    }
});
