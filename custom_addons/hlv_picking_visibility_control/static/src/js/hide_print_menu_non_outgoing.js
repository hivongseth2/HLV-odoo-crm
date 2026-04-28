/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { onMounted, onPatched, onWillUnmount } from "@odoo/owl";

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        this._hlvPrintObserver = null;
        onMounted(() => this._hlvHidePrintMenuForNonOutgoing());
        onPatched(() => this._hlvHidePrintMenuForNonOutgoing());
        onWillUnmount(() => {
            if (this._hlvPrintObserver) {
                this._hlvPrintObserver.disconnect();
                this._hlvPrintObserver = null;
            }
        });
    },

    _hlvHidePrintMenuForNonOutgoing() {
        if (this.props?.resModel !== "stock.picking") {
            return;
        }

        const data = this.model?.root?.data || {};
        const isOutgoing = data.picking_type_code === "outgoing";

        const normalize = (text) =>
            (text || "")
                .replace(/\s+/g, " ")
                .trim()
                .toLowerCase();

        const isPrintLabel = (text) => {
            const label = normalize(text);
            return label === "in" || label === "print" || label.startsWith("in ") || label.startsWith("print ");
        };

        const applyFilter = () => {
            const items = document.querySelectorAll(
                ".o_cp_action_menus .dropdown-item, .o_cp_action_menus [role='menuitem'], .o_control_panel .dropdown-item, .o_control_panel [role='menuitem']"
            );

            items.forEach((item) => {
                if (!isPrintLabel(item.textContent)) {
                    return;
                }

                const container = item.closest("li, .dropdown-item, .o-dropdown-item, [role='none']") || item;
                if (isOutgoing) {
                    if (container.dataset.hlvPrintHidden === "1") {
                        container.style.removeProperty("display");
                        delete container.dataset.hlvPrintHidden;
                    }
                } else {
                    container.style.setProperty("display", "none", "important");
                    container.dataset.hlvPrintHidden = "1";
                }
            });

            const headerButtons = document.querySelectorAll(
                ".o_form_view .o_form_statusbar button, .o_form_view header button, .o_form_view .o_statusbar_buttons button"
            );
            headerButtons.forEach((btn) => {
                const label = normalize(btn.textContent);
                const isPrintButton = label === "in" || label.includes("in bi") || label.includes("print");
                if (!isPrintButton) {
                    return;
                }

                if (isOutgoing) {
                    if (btn.dataset.hlvPrintHidden === "1") {
                        btn.style.removeProperty("display");
                        delete btn.dataset.hlvPrintHidden;
                    }
                } else {
                    btn.style.setProperty("display", "none", "important");
                    btn.dataset.hlvPrintHidden = "1";
                }
            });
        };

        applyFilter();

        if (!this._hlvPrintObserver) {
            this._hlvPrintObserver = new MutationObserver(() => {
                if (this.props?.resModel === "stock.picking") {
                    applyFilter();
                }
            });
            this._hlvPrintObserver.observe(document.body, {
                childList: true,
                subtree: true,
            });
        }
    },
});
