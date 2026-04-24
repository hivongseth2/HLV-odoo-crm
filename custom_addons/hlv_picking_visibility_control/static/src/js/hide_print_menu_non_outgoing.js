/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { onMounted, onPatched } from "@odoo/owl";

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        onMounted(() => this._hlvHidePrintMenuForNonOutgoing());
        onPatched(() => this._hlvHidePrintMenuForNonOutgoing());
    },

    _hlvHidePrintMenuForNonOutgoing() {
        if (this.props?.resModel !== "stock.picking") {
            return;
        }

        const data = this.model?.root?.data || {};
        if (data.picking_type_code === "outgoing") {
            return;
        }

        const candidates = [
            ".o_cp_action_menus .dropdown-toggle",
            ".o_cp_action_menu .dropdown-toggle",
            ".o_control_panel .o-dropdown button.dropdown-toggle",
        ];

        for (const selector of candidates) {
            document.querySelectorAll(selector).forEach((btn) => {
                const label = (btn.textContent || "").trim().toLowerCase();
                if (label === "in" || label.includes("in ")) {
                    btn.style.setProperty("display", "none", "important");
                }
            });
        }
    },
});
