/** @odoo-module **/

import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";

/**
 * HLV POS IndexedDB Recovery
 * This script catches 'NotFoundError' which occurs when IndexedDB object stores 
 * are missing (common after model changes or module uninstalls in Odoo 18).
 */

const DB_NAME = "pos-db";

// Handle global unhandled rejections (most IndexedDB errors in Odoo 18 show up here)
window.addEventListener("unhandledrejection", (event) => {
    const error = event.reason;
    if (error && error.name === "NotFoundError" && (error.message.includes("object store") || error.message.includes("transaction"))) {
        console.error("[HLV POS FIX] Missing IndexedDB store detected. Deleting DB and reloading...");

        // Use a flag to avoid infinite reload loops
        const lastFix = browser.localStorage.getItem("hlv_pos_fix_time");
        const now = Date.now();
        if (lastFix && (now - parseInt(lastFix)) < 10000) {
            console.warn("[HLV POS FIX] Fix recently applied, skipping to avoid loop.");
            return;
        }
        browser.localStorage.setItem("hlv_pos_fix_time", now.toString());

        try {
            // Delete the pos-db to force a clean sync
            window.indexedDB.deleteDatabase(DB_NAME);

            // Wait a moment and reload
            setTimeout(() => {
                browser.location.reload();
            }, 1000);
        } catch (e) {
            browser.location.reload();
        }
    }
});

console.log("[HLV POS FIX] IndexedDB Safeguard Active in Return Source Location module.");
