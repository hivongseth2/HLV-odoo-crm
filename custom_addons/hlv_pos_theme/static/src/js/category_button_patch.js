/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { CategoryButton } from "@point_of_sale/app/generic_components/category_button/category_button";

// Patch CategoryButton to override the inline style for background color
patch(CategoryButton.prototype, {
    /**
     * Override the get style method to return a clean, neutral color
     * instead of the default dynamic color calculation.
     */
    get style() {
        // Return a clean, neutral white background instead of colorful ones
        return "background-color: #f8f9fa; color: #212529;";
    },
});
