/** @odoo-module **/

import { useEffect } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";

/**
 * Clean Patch: Aggressively removes inline colors.
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
        const cleanup = () => {
            // Target all category buttons
            const categoryButtons = document.querySelectorAll('.category-button');
            categoryButtons.forEach((btn) => {
                // Remove ALL inline styles that might interfere
                btn.removeAttribute('style');

                // Add our theme class
                btn.classList.add('hlv-clean-category');

                // Also clean up children if they have weird styles (sometimes icons/spans do)
                const children = btn.querySelectorAll('*');
                children.forEach(child => {
                    // Only remove background/color from children, keep layout stuff if needed
                    child.style.removeProperty('background-color');
                    child.style.removeProperty('color');
                    child.style.removeProperty('background');
                });
            });
        };

        // Run repeatedly to catch Odoo's dynamic rendering
        setTimeout(cleanup, 50);
        setTimeout(cleanup, 200);
        setTimeout(cleanup, 500);
        setTimeout(cleanup, 1000);

        // Also observe mutations if possible, but this simple loop is usually enough for POS
        // For robustness, let's try a mutation observer on the category list container if we can find it
        const catList = document.querySelector('.products-widget-control-panel .categories');
        if (catList) {
            const observer = new MutationObserver(cleanup);
            observer.observe(catList, { childList: true, subtree: true });
        }
    },
});
