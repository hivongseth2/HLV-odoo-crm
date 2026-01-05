/** @odoo-module */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { ErrorPopup } from "@point_of_sale/app/errors/error_popup/error_popup";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(PaymentScreen.prototype, {
    async validateOrder(isForceValidate) {
        console.log("DEBUG: validateOrder called in patch");
        const partner = this.currentOrder.get_partner();
        console.log("DEBUG: Current partner:", partner);

        if (!partner) {
            console.log("DEBUG: No partner selected, blocking validation");
            this.env.services.popup.add(ErrorPopup, {
                title: _t('Customer Required'),
                body: _t('Please select a customer to proceed with the order.'),
            });
            return;
        }
        await super.validateOrder(isForceValidate);
    }
});
