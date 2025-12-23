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
     * HACK: DOM Surgery (V2 - Aggressive Move)
     * 1. Detect if Sidebar exists (Control Panel).
     * 2. Detect Category List.
     * 3. MOVE Category List INTO Sidebar.
     * 4. Style everything.
     */
    _cleanCategoryButtonStyles() {
        const performSurgery = () => {
            // 1. Identify Key Elements
            // .products-widget-control-panel is usually the top bar in Odoo 17+, but likely acts as our sidebar target due to CSS
            // .pos-rightheader might be another target, but let's stick to what we know exists
            const controlPanel = document.querySelector('.products-widget-control-panel');
            const productListContainer = document.querySelector('.product-list-container');
            const categoryButtons = document.querySelectorAll('.category-button');

            if (!controlPanel || categoryButtons.length === 0) return;

            // 2. Identify the Category Container
            // We assume the parent of the first button is the container
            const categoryContainer = categoryButtons[0].parentElement;

            // 3. Move Category Container into Control Panel (Sidebar)
            // Only if certain conditions met:
            // - It's not already there
            // - We confirm it's the right container (has buttons)
            if (categoryContainer && !controlPanel.contains(categoryContainer)) {
                console.log('[HLV Theme] Moving Categories into Sidebar...');

                // APPEND to Sidebar
                controlPanel.appendChild(categoryContainer);

                // Apply sidebar-specific styles to the container
                categoryContainer.classList.add('hlv-category-list-moved');

                // Force container styles
                categoryContainer.style.cssText = `
                     display: flex !important;
                     flex-direction: column !important;
                     gap: 5px !important;
                     width: 100% !important;
                     padding: 5px 0 !important;
                     overflow-y: auto !important;
                 `;
            }

            // 4. Style the Buttons (List View)
            categoryButtons.forEach((btn) => {
                btn.classList.add('hlv-clean-category');
                btn.style.cssText = `
                     width: 100% !important;
                     text-align: left !important;
                     justify-content: flex-start !important;
                     display: flex !important;
                     align-items: center !important;
                     margin: 2px 0 !important;
                     padding: 10px 15px !important;
                     background-color: #fff !important;
                     color: #333 !important;
                     border: 1px solid #e0e0e0 !important;
                     border-radius: 6px !important;
                 `;

                // Fix text alignment inside button
                const textSpan = btn.querySelector('span') || btn.querySelector('div');
                if (textSpan) {
                    textSpan.style.textAlign = 'left';
                    textSpan.style.width = '100%';
                }
            });

            // 5. Ensure Layout Structure (CSS Backup)
            // Force Control Panel to be a Sidebar
            if (controlPanel) {
                controlPanel.style.cssText = `
                    display: flex !important;
                    flex-direction: column !important;
                    width: 280px !important;
                    min-width: 280px !important;
                    height: 100% !important;
                    overflow-y: auto !important;
                    border-right: 1px solid #ddd !important;
                    background-color: #fff !important;
                    position: relative !important;
                    z-index: 10 !important;
                `;
            }

            // Force Product List to take remaining space
            if (productListContainer) {
                productListContainer.style.cssText = `
                    flex: 1 !important;
                    width: auto !important;
                    margin-left: 0 !important;
                    height: 100% !important;
                    overflow-y: auto !important;
                 `;
            }
        };

        // Run repeatedly to handle dynamic re-rendering by Odoo
        setTimeout(performSurgery, 100);
        setTimeout(performSurgery, 500);
        setTimeout(performSurgery, 1500);

        // Continuous check for 5 seconds to catch delayed renders (common in POS loading)
        let attempts = 0;
        const interval = setInterval(() => {
            performSurgery();
            attempts++;
            if (attempts > 20) clearInterval(interval);
        }, 250);
    },
});
