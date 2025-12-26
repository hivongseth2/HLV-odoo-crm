/** @odoo-module **/

import { ProductCard } from "@point_of_sale/app/generic_components/product_card/product_card";
import { patch } from "@web/core/utils/patch";
import { onMounted, onPatched } from "@odoo/owl";

console.log("[HLV POS THEME] Loading ProductCard patch...");

patch(ProductCard.prototype, {
    setup() {
        super.setup();
        const updatePrice = () => {
            try {
                // Check if price exists in DOM to avoid duplicates
                if (this.__hlv_price_injected) return;

                // Find valid host element (Owl 2 component root)
                // Use this.imageRef or check internal DOM refs if available, or just queryselector on document if unique ID is known? 
                // Better: use the ref if ProductCard exposes one, or find node by rendering context.
                // Since we can't easily get 'this.el' in setup(), we use onMounted.

                // Actually, in Owl 2, 'this.el' isn't direct. 
                // We'll try to rely on the fact that ProductCard is simple.
                // But we can't easily query DOM of *this* component without a ref.

                // However, we DO have the product data!
                const product = this.props.product;
                if (!product) return;

                // Let's modify the DOM "blindly" if we can find our ID?
                // ProductCard usually renders a div.
                // In Odoo 18, we can find it by specific attributes?

                // Alternative: use DOM query for data-product-id matching this product
                const cardEl = document.querySelector(`.product[data-product-id="${product.id}"]`);
                if (cardEl) {
                    const contentDiv = cardEl.querySelector('.product-content');
                    if (!contentDiv) {
                        // console.warn("[HLV POS THEME] contentDiv not found for product", product.id);
                        return;
                    }

                    let priceEl = contentDiv.querySelector('.hlv-price-forced');

                    if (!priceEl) {
                        // Get formatted price
                        let priceText = "";
                        if (this.props.formattedPrice) {
                            priceText = this.props.formattedPrice;
                        } else if (typeof product.get_formatted_price === 'function') {
                            priceText = product.get_formatted_price();
                        } else if (this.env?.services?.pos) {
                            // Safe access to pos service
                            priceText = this.env.services.pos.format_currency(product.lst_price);
                        } else {
                            priceText = product.lst_price + " ₫";
                        }

                        priceEl = document.createElement('div');
                        priceEl.className = 'product-price hlv-price-forced';
                        priceEl.innerText = priceText;

                        // Style inline just in case
                        priceEl.style.color = '#dc2626';
                        priceEl.style.fontWeight = 'bold';
                        priceEl.style.display = 'block';

                        contentDiv.appendChild(priceEl);
                        this.__hlv_price_injected = true;
                    }
                }
            } catch (e) {
                console.error("[HLV POS THEME ERROR] Failed to update price for product card:", e);
                // Do not re-throw, to avoid killing the component
            }
        };

        onMounted(updatePrice);
        onPatched(updatePrice);
    }
});
