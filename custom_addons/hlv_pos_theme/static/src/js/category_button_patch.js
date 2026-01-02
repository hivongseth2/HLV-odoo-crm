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
            () => [this.env.services.pos.selectedCategoryId]
        );
    },

    _cleanCategoryButtonStyles() {
        const cleanup = () => {
            // 0. ENSURE LAYOUT CLASS
            const catList = document.querySelector('.category-list') || document.querySelector('.category-button')?.parentElement;
            const prodList = document.querySelector('.product-list:not(.category-list)') || document.querySelector('article.product')?.parentElement;

            if (catList && prodList) {
                const commonParent = catList.parentElement;
                if (commonParent) {
                    commonParent.classList.add('hlv-sidebar-layout');
                }
            } else {
                const productsWidget = document.querySelector('.products-widget');
                if (productsWidget) {
                    productsWidget.classList.add('hlv-sidebar-layout');
                }
            }

            // 1. CLEAN CATEGORY BUTTONS
            const categoryButtons = document.querySelectorAll('.category-button');

            // Get Selected Category ID from POS Service
            const selectedCategoryId = this.env.services.pos.selectedCategoryId;

            categoryButtons.forEach((btn) => {
                btn.removeAttribute('style');
                btn.classList.add('hlv-clean-category');

                // 3. ROBUST ID-BASED LOGIC
                // Requires data-category-id from XML override
                const btnId = parseInt(btn.getAttribute('data-category-id') || btn.getAttribute('data-id'));

                if (btnId && selectedCategoryId && this.env.services.pos.db) {
                    const db = this.env.services.pos.db;
                    const selectedCategory = db.get_category_by_id(selectedCategoryId);

                    let isActive = false;
                    let isDimmed = false;

                    // CASE A: Direct Selection
                    if (btnId === selectedCategoryId) {
                        isActive = true;
                    }
                    // CASE B: Parent Selection (Show children as active)
                    // If the selected category is the PARENT of this button, this button matches.
                    else if (selectedCategory && selectedCategory.id === db.get_category_parent_id(btnId)) {
                        isActive = true;
                    }
                    // CASE C: Child Selection (I am the parent of the selected category)
                    // (Optional, not requested but good practice)

                    // CASE D: Sibling Logic (Explicit Dimming)
                    // If I am NOT active, but my Sibling IS selected, I should be Dimmed (Gray).
                    if (!isActive) {
                        // Check if I share a parent with the selected category
                        const myParentId = db.get_category_parent_id(btnId);
                        const selectedParentId = selectedCategory ? db.get_category_parent_id(selectedCategory.id) : null;

                        // If I share a parent with the Active Category, but I am not Active -> Dim me.
                        if (myParentId === selectedParentId) {
                            isDimmed = true;
                        }
                    }

                    // APPLY CLASSES
                    if (isActive) {
                        btn.classList.add('hlv-active-category');
                        btn.classList.remove('hlv-dimmed-category');
                        btn.classList.remove('opacity-50'); // Force clear Odoo dim
                        btn.classList.add('selected');
                    } else if (isDimmed) {
                        btn.classList.remove('hlv-active-category');
                        btn.classList.add('hlv-dimmed-category');
                        btn.classList.add('opacity-50'); // Ensure Odoo dim
                        btn.classList.remove('selected');
                    } else {
                        // Neutral (Root or Unrelated)
                        btn.classList.remove('hlv-active-category');
                        btn.classList.remove('hlv-dimmed-category');
                        // Let Odoo handle opacity for unrelated items or force clear if needed
                        // btn.classList.remove('opacity-50'); 
                        btn.classList.remove('selected');
                    }

                } else {
                    // Fallback to opacity check if data-id missing or DB not ready
                    const hasSelection = document.querySelector('.category-button.opacity-50');
                    if (hasSelection) {
                        if (!btn.classList.contains('opacity-50')) {
                            btn.classList.add('hlv-active-category');
                            btn.classList.add('selected');
                        } else {
                            btn.classList.remove('hlv-active-category');
                            btn.classList.remove('selected');
                        }
                    } else {
                        btn.classList.remove('hlv-active-category');
                        btn.classList.remove('selected');
                    }
                }

                // Remove Odoo color classes
                const classes = [...btn.classList];
                classes.forEach(cls => {
                    if (cls.startsWith('o_colorlist_')) {
                        btn.classList.remove(cls);
                    }
                });

                // Clean children
                const children = btn.querySelectorAll('*');
                children.forEach(child => {
                    child.style.removeProperty('background-color');
                    child.style.removeProperty('color');
                    child.style.removeProperty('background');
                });
            });

            // 2. CLEAN PRODUCT CARDS & INJECT PRICE
            const productCards = document.querySelectorAll('.product');
            productCards.forEach((card) => {
                card.classList.add('hlv-product-card');

                // Color Cleanup
                const classes = [...card.classList];
                classes.forEach(cls => {
                    if (cls.startsWith('o_colorlist_')) {
                        card.classList.remove(cls);
                    }
                });
                card.style.removeProperty('background-color');
                card.style.removeProperty('background');

                const img = card.querySelector('.product-img');
                if (img) {
                    img.style.removeProperty('background-color');
                    img.style.removeProperty('background');
                }

                // 3. FORCE PRICE INJECTION
                let priceEl = card.querySelector('.price-tag, .product-price, .product-price-tag, span[class*="price"], .hlv-price-forced');

                // If missing, CREATE IT
                if (!priceEl) {
                    const productId = card.getAttribute('data-product-id');

                    // SAFETY CHECK: Ensure DB exists before accessing
                    if (productId && this.env && this.env.services && this.env.services.pos && this.env.services.pos.db) {
                        try {
                            const product = this.env.services.pos.db.get_product_by_id(parseInt(productId));
                            if (product) {
                                let priceText = "";
                                if (typeof this.env.services.pos.format_currency === 'function') {
                                    priceText = this.env.services.pos.format_currency(product.lst_price);
                                } else {
                                    priceText = product.lst_price + " ₫";
                                }

                                const contentDiv = card.querySelector('.product-content');
                                if (contentDiv) {
                                    priceEl = document.createElement('div');
                                    priceEl.className = 'product-price hlv-price-forced';
                                    priceEl.innerText = priceText;
                                    contentDiv.appendChild(priceEl);
                                }
                            }
                        } catch (e) {
                            console.warn("[HLV Theme] Price inject failed: ", e);
                        }
                    } else if (productId) {
                        // DB not available (common in Odoo 18 ProductScreen setup)
                        // We rely on product_card_patch.js to handle this now.
                    }
                } else {
                    priceEl.classList.add('hlv-price-forced');
                    priceEl.style.color = '#dc2626';
                    priceEl.style.fontWeight = 'bold';
                    priceEl.style.display = 'block';
                    priceEl.style.visibility = 'visible';
                }
            });
        };

        // Run repeatedly
        setTimeout(cleanup, 50);
        setTimeout(cleanup, 200);
        setTimeout(cleanup, 500);
        setTimeout(cleanup, 1000);
        setTimeout(cleanup, 3000);

        const screen = document.querySelector('.product-screen') || document.querySelector('.pos-content');
        if (screen) {
            const observer = new MutationObserver(cleanup);
            observer.observe(screen, { childList: true, subtree: true });
        }
    },
});
