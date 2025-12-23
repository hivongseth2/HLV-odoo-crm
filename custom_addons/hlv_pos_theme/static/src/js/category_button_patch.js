/** @odoo-module **/

import { useEffect } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";

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
        // Run multiple times to ensure we catch lazy-loaded elements
        const cleanup = () => {
            const categoryButtons = document.querySelectorAll('.category-button');
            categoryButtons.forEach((btn) => {
                // 1. Remove inline colors
                btn.style.removeProperty('background-color');
                btn.style.removeProperty('background');
                btn.style.removeProperty('color');

                // 2. Add marker class
                btn.classList.add('hlv-clean-category');

                // 3. Force inline styles for structure (just in case CSS isn't loaded yet)
                // This ensures immediate visual feedback
                btn.style.setProperty('justify-content', 'flex-start', 'important');
                btn.style.setProperty('text-align', 'left', 'important');
            });
        };

        setTimeout(cleanup, 50);
        setTimeout(cleanup, 300);
        setTimeout(cleanup, 1000); // Late load
    },
});
