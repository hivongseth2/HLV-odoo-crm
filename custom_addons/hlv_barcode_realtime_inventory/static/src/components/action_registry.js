/** @odoo-module */

import { registry } from "@web/core/registry";
import { InventoryCheckScanner } from "./inventory_check/inventory_check";

// Register the OWL component
registry.category("actions").add("hlv_inventory_check_scanner", InventoryCheckScanner);
