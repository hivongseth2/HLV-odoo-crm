/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { MainMenu } from "@stock_barcode/main_menu";
import { onMounted, onPatched } from "@odoo/owl";

patch(MainMenu.prototype, {
    setup() {
        super.setup(...arguments);
        this._hlvHideInventoryDone = false;
        onMounted(() => this._hlvHideInventoryBtn());
        onPatched(() => this._hlvHideInventoryBtn());
    },

    _hlvHideInventoryBtn() {
        if (this._hlvHideInventoryDone) return;
        const btns = document.querySelectorAll(".o_button_inventory");
        btns.forEach((btn) => {
            btn.style.setProperty("display", "none", "important");
            this._hlvHideInventoryDone = true;
        });
        // Retry once if button not yet rendered
        if (!this._hlvHideInventoryDone) {
            setTimeout(() => {
                document.querySelectorAll(".o_button_inventory").forEach((btn) => {
                    btn.style.setProperty("display", "none", "important");
                });
            }, 500);
        }
    },
});
