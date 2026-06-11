/** @odoo-module **/

import { mount, whenReady } from "@odoo/owl";
import { BarcodeShipperApp } from "./components/barcode_shipper_app";
import { templates } from "@web/core/assets";

whenReady(async () => {
    const root = document.getElementById("shipper_app_root_v2");
    if (root) {
        try {
            await mount(BarcodeShipperApp, root, { templates, dev: true });
            console.log("Barcode Shipper OWL App V2 mounted successfully!");
        } catch (e) {
            console.error("Error mounting Barcode Shipper V2 app:", e);
        }
    }
});
