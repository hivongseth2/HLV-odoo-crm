/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { MainMenu } from "@stock_barcode/main_menu";
import { onMounted, onPatched } from "@odoo/owl";

patch(MainMenu.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(() => this._hideInventoryButton());
        onPatched(() => this._hideInventoryButton());
    },

    _hideInventoryButton() {
        const btn = document.querySelector(".o_button_inventory");
        if (btn) {
            btn.style.display = "none";
        }
    },
});
