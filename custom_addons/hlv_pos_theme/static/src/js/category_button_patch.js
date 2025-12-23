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

    /**
     * HACK: Force Layout via JavaScript
     * Since CSS selectors are failing usually due to Odoo 18 DOM changes,
     * we manually find the elements and force the styles.
     */
    _cleanCategoryButtonStyles() {
        const cleanup = () => {
            const categoryButtons = document.querySelectorAll('.category-button');
            if (categoryButtons.length === 0) return;

            // 1. STYLE INDIVIDUAL BUTTONS
            categoryButtons.forEach((btn) => {
                btn.classList.add('hlv-clean-category');
                btn.style.cssText = `
                     width: 100% !important;
                     display: flex !important;
                     justify-content: flex-start !important;
                     text-align: left !important;
                     margin: 4px 0 !important;
                     background-color: #fff !important;
                     color: #333 !important;
                     border: 1px solid #e0e0e0 !important;
                     border-radius: 6px !important;
                     padding: 10px !important;
                     font-size: 14px !important;
                 `;
            });

            // 2. FIND CONTAINER AND FORCE SIDEBAR MODE
            // We work up from the button to find the container
            const container = categoryButtons[0].parentElement;
            if (container && !container.classList.contains('hlv-sidebar-active')) {
                container.classList.add('hlv-sidebar-active');

                // Force container to be fixed sidebar on left
                container.style.cssText = `
                     display: flex !important;
                     flex-direction: column !important;
                     width: 260px !important;
                     min-width: 260px !important;
                     height: 100% !important;
                     overflow-y: auto !important;
                     padding: 10px !important;
                     background-color: #fff !important;
                     border-right: 1px solid #ddd !important;
                     position: absolute !important;
                     left: 0 !important;
                     top: 0 !important;
                     z-index: 90 !important;
                 `;

                // 3. PUSH PRODUCT LIST TO RIGHT
                // Try to find the sibling or parent wrapper to push content
                // In standard POS, product list is usually a sibling or close by

                // Strategy: Make the PARENT flex so they sit side-by-side
                const wrapper = container.parentElement;
                if (wrapper) {
                    // Check if wrapper has the product list
                    // If we are "position: absolute", we need to margin-left the sibling
                    const productList = wrapper.querySelector('.product-list-container') || wrapper.querySelector('.product-list');
                    if (productList) {
                        productList.style.marginLeft = '260px'; // Push distinct right
                        productList.style.width = 'calc(100% - 260px)';
                    } else {
                        // Fallback global search if structure is weird
                        const globalProductList = document.querySelector('.product-list-container');
                        if (globalProductList) {
                            globalProductList.style.marginLeft = '260px';
                            globalProductList.style.width = 'calc(100% - 260px)';
                        }
                    }
                }
            }
        };

        // Aggressive loop to ensure it sticks during renders
        setTimeout(cleanup, 100);
        setTimeout(cleanup, 500);
        setTimeout(cleanup, 1000);
        setTimeout(cleanup, 2000);
    },
});
