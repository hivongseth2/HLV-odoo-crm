/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { MainMenu } from "@stock_barcode/main_menu";
import { onMounted, onPatched } from "@odoo/owl";

patch(MainMenu.prototype, {
    setup() {
        super.setup(...arguments);
        this._shouldHideInventory = false;
        this._checkInventoryAccess();
        onMounted(() => this._applyInventoryVisibility());
        onPatched(() => this._applyInventoryVisibility());
    },

    async _checkInventoryAccess() {
        const userService = this.env.services.user;
        const allowed = await userService.hasGroup(
            "hlv_barcode_inventory_control.group_barcode_inventory_button"
        );
        if (!allowed) {
            this._shouldHideInventory = true;
            this._applyInventoryVisibility();
        }
    },

    _applyInventoryVisibility() {
        if (!this._shouldHideInventory) return;
        const btn = document.querySelector(".o_button_inventory");
        if (btn) {
            btn.style.display = "none";
        }
    },
});
