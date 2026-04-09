/** @odoo-module */

import { registry } from "@web/core/registry";
import { HlvBarcodeApp } from "./barcode_app/barcode_app";

registry.category("actions").add("hlv_barcode_custom_app", HlvBarcodeApp);
