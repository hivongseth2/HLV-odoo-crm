/** @odoo-module **/

import { mount, whenReady } from "@odoo/owl";
import { BarcodeShipperApp } from "./components/barcode_shipper_app";
import { templates } from "@web/core/assets";
import { loadJS } from "@web/core/network/download";

whenReady(async () => {
    const root = document.getElementById("shipper_app_root_v2");
    if (root) {
        try {
            // Đảm bảo barcode-detector polyfill được load
            await loadJS("https://fastly.jsdelivr.net/npm/barcode-detector@3/dist/iife/polyfill.min.js");
            
            await mount(BarcodeShipperApp, root, { templates, dev: true });
            console.log("Barcode Shipper OWL App V2 mounted successfully!");
        } catch (e) {
            console.error("Error mounting Barcode Shipper V2 app:", e);
        }
    }
});
