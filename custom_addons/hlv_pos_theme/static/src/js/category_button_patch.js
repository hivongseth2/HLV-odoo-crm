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
            // 0. ENSURE LAYOUT CLASS (XML replacement)
            const productsWidget = document.querySelector('.products-widget');
            if (productsWidget) {
                productsWidget.classList.add('hlv-sidebar-layout');
            }

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

            // 2. CLEAN PRODUCT CARDS & FORCE PRICE
            const productCards = document.querySelectorAll('.product');
            productCards.forEach((card) => {
                // CLEAN CARD BG
                card.style.removeProperty('background-color');
                card.style.removeProperty('background');

                // CLEAN IMG BG
                const img = card.querySelector('.product-img');
                if (img) {
                    img.style.removeProperty('background-color');
                    img.style.removeProperty('background');
                }

                // FORCE PRICE VISIBILITY
                // Try multiple common selectors for Odoo POS prices
                const priceEl = card.querySelector('.price-tag, .product-price, .product-price-tag, span[class*="price"]');
                if (priceEl) {
                    priceEl.classList.add('hlv-price-forced');
                    // Force inline styles as a backup against extreme CSS specificity issues
                    priceEl.style.color = '#dc2626'; // Red
                    priceEl.style.fontWeight = 'bold';
                    priceEl.style.fontSize = '16px';
                    priceEl.style.display = 'block';
                    priceEl.style.visibility = 'visible';
                    priceEl.style.opacity = '1';
                }
            });
        };

        // Run repeatedly to catch Odoo's dynamic rendering
        setTimeout(cleanup, 50);
        setTimeout(cleanup, 200);
        setTimeout(cleanup, 500);
        setTimeout(cleanup, 1000);
        setTimeout(cleanup, 3000); // Late cleaning for slow loaders

        // Also observe mutations if possible
        const productsWidget = document.querySelector('.products-widget');
        if (productsWidget) {
            const observer = new MutationObserver(cleanup);
            observer.observe(productsWidget, { childList: true, subtree: true });
        }
    },
});
