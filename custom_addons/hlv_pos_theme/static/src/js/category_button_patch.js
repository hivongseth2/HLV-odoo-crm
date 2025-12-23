/** @odoo-module **/

import { useEffect } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";

/**
 * Clean Patch: Only removes inline colors.
 * Layout is handled by CSS (hlv-sidebar-layout).
 */
patch(ProductScreen.prototype, {
    setup() {
        super.setup();
        useEffect(
            () => {
                this._cleanCategoryButtonStyles();
            },
            () => []
        );
    },

    _cleanCategoryButtonStyles() {
        // Simple, robust cleanup
        const cleanup = () => {
            const categoryButtons = document.querySelectorAll('.category-button');
            categoryButtons.forEach((btn) => {
                // 1. Remove inline colors that conflict with our theme
                btn.style.setProperty('background-color', '', 'important');
                btn.style.removeProperty('background-color');
                btn.style.removeProperty('background');
                btn.style.removeProperty('color');

                // 2. Add class for CSS
                btn.classList.add('hlv-clean-category');
            });
        };

        // Run a few times to catch render cycles
        setTimeout(cleanup, 50);
        setTimeout(cleanup, 200);
        setTimeout(cleanup, 1000);
    },
});
