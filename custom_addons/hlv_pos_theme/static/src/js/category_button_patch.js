/** @odoo-module **/

/**
 * This script removes the inline background-color styles from POS category buttons
 * after they are rendered, allowing CSS to take over.
 * 
 * We use MutationObserver to watch for DOM changes and clean up the styles.
 */

import { onMounted, onPatched, useEffect } from "@odoo/owl";
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
     * Remove inline background-color and color styles from category buttons
     * This allows our CSS to take control
     */
    _cleanCategoryButtonStyles() {
        // Delay slightly to ensure DOM is fully rendered
        setTimeout(() => {
            const categoryButtons = document.querySelectorAll('.category-button');
            categoryButtons.forEach((btn) => {
                // Remove inline style attributes that override CSS
                btn.style.removeProperty('background-color');
                btn.style.removeProperty('background');
                btn.style.removeProperty('color');

                // Add our custom class for styling
                btn.classList.add('hlv-clean-category');
            });
        }, 100);
    },
});
