/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";

/**
 * HLV POS IndexedDB Recovery Patch
 * Detects 'NotFoundError' on object stores and forces a database rebuild.
 * This is a common issue in Odoo 18 when custom models are added.
 */

const DB_NAME = "pos-db";

const originalOpen = window.indexedDB.open;
window.indexedDB.open = function (name, version) {
    const request = originalOpen.apply(this, arguments);

    // We don't want to interfere with standard Odoo logic too much,
    // but we can listen for errors that happen later.
    return request;
};

// Listen for uncaught promise rejections that match our specific error
window.addEventListener("unhandledrejection", async (event) => {
    const error = event.reason;
    if (error && error.name === "NotFoundError" && error.message.includes("object store")) {
        console.error("[HLV POS FIX] Detected missing IndexedDB object store. Attempting recovery...");

        // Show a helpful notification if possible
        const msg = _t("Lỗi dữ liệu trình duyệt (IndexedDB). Hệ thống sẽ tự động đặt lại bộ nhớ POS sau 3 giây để sửa lỗi này.");
        if (window.alert) {
            // Use standard alert if Owl/Services not ready
            alert(msg);
        }

        try {
            // Delete the database to force Odoo to recreate it with the new schema
            const deleteRequest = window.indexedDB.deleteDatabase(DB_NAME);
            deleteRequest.onsuccess = () => {
                console.log("[HLV POS FIX] Database deleted successfully. Reloading...");
                browser.location.reload();
            };
            deleteRequest.onerror = () => {
                console.error("[HLV POS FIX] Failed to delete database.");
                browser.location.reload(); // Reload anyway as a fallback
            };
        } catch (e) {
            browser.location.reload();
        }
    }
});

console.log("[HLV POS FIX] IndexedDB Safeguard Loaded.");
