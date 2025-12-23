/** @odoo-module **/

/**
 * This script removes the inline background-color styles from POS category buttons
 * after they are rendered, and applies clean styling directly.
 */

import { useEffect } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";

patch(ProductScreen.prototype, {
    setup() {
        super.setup();

        // Use useEffect to run after each render
        useEffect(
            () => {
                this._cleanCategoryButtonStyles();
            },
            () => []  // Dependencies - run on every render
        );
    },

    /**
     * Remove inline background-color and apply clean styles
     */
    _cleanCategoryButtonStyles() {
        // Delay slightly to ensure DOM is fully rendered
        setTimeout(() => {
            const categoryButtons = document.querySelectorAll('.category-button');
            categoryButtons.forEach((btn) => {
                // Remove inline style attributes
                btn.style.removeProperty('background-color');
                btn.style.removeProperty('background');
                btn.style.removeProperty('color');

                // Add our custom class
                btn.classList.add('hlv-clean-category');

                // Apply inline styles directly (guaranteed to work)
                btn.style.setProperty('background-color', '#ffffff', 'important');
                btn.style.setProperty('color', '#333333', 'important');
                btn.style.setProperty('border', '1px solid #e0e0e0', 'important');
                btn.style.setProperty('border-radius', '8px', 'important');
                btn.style.setProperty('box-shadow', '0 1px 3px rgba(0,0,0,0.08)', 'important');
            });
        }, 50);

        // Run again after a longer delay in case of lazy loading
        setTimeout(() => {
            const categoryButtons = document.querySelectorAll('.category-button');
            categoryButtons.forEach((btn) => {
                btn.style.removeProperty('background-color');
                btn.style.removeProperty('background');
                btn.style.setProperty('background-color', '#ffffff', 'important');
                btn.style.setProperty('color', '#333333', 'important');
                btn.style.setProperty('border', '1px solid #e0e0e0', 'important');
                btn.style.setProperty('border-radius', '8px', 'important');
            });
        }, 500);
    },
});
