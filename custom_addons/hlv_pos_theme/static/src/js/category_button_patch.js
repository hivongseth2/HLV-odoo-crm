/** @odoo-module **/
console.log("[HLV POS THEME] JS Loaded - Patching ProductScreen...");

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
            // 1. CLEAN CATEGORY BUTTONS
            const categoryButtons = document.querySelectorAll('.category-button');
            categoryButtons.forEach((btn) => {
                btn.removeAttribute('style');
                btn.classList.add('hlv-clean-category');

                // Clean children
                const children = btn.querySelectorAll('*');
                children.forEach(child => {
                    child.style.removeProperty('background-color');
                    child.style.removeProperty('color');
                    child.style.removeProperty('background');
                });
            });

            // 2. CLEAN PRODUCT CARDS (Remove random background colors)
            const productCards = document.querySelectorAll('.product');
            productCards.forEach((card) => {
                // Odoo puts bg color on the card itself often
                card.style.removeProperty('background-color');
                card.style.removeProperty('background');

                // Also inner image container if needed
                const img = card.querySelector('.product-img');
                if (img) {
                    img.style.removeProperty('background-color');
                    img.style.removeProperty('background');
                }
            });
        };

        // Run repeatedly to catch Odoo's dynamic rendering
        setTimeout(cleanup, 50);
        setTimeout(cleanup, 200);
        setTimeout(cleanup, 500);
        setTimeout(cleanup, 1000);

        // Also observe mutations if possible, but this simple loop is usually enough for POS
        // For robustness, let's try a mutation observer on the category list container if we can find it
        const productsWidget = document.querySelector('.products-widget');
        if (productsWidget) {
            const observer = new MutationObserver(cleanup);
            observer.observe(productsWidget, { childList: true, subtree: true });
        }
    },
});
