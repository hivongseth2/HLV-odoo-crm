/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { useService } from "@web/core/utils/hooks";
import { PrintReportPopup } from "./print_report_popup";

patch(ReceiptScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.dialog = useService("dialog");
    },

    openHlvReportPopup() {
        const order = this.pos.get_order();
        if (!order) {
            this.notification.add("Không tìm thấy đơn hàng", { type: "warning" });
            return;
        }

        this.dialog.add(PrintReportPopup, {
            order: order,
        });
    },
});
