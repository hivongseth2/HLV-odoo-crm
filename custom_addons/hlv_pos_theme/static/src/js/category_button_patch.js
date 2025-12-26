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
            categoryButtons.forEach((btn) => {
                btn.removeAttribute('style');
                btn.classList.add('hlv-clean-category');

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
                    if (productId && this.env && this.env.services && this.env.services.pos) {
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
