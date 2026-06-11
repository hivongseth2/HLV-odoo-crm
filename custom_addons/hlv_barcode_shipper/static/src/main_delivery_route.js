/** @odoo-module **/

import { mount, whenReady } from "@odoo/owl";
import { templates } from "@web/core/assets";
import { DeliveryRouteApp } from "./components/delivery_route/delivery_route_app";

whenReady(async () => {
    const root = document.getElementById("shipper_delivery_route_root");
    if (!root) {
        return;
    }
    try {
        await mount(DeliveryRouteApp, root, { templates, dev: false });
    } catch (error) {
        console.error("Error mounting delivery route app:", error);
    }
});
