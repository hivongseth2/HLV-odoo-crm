/** @odoo-module **/

import { browser } from "@web/core/browser/browser";

/**
 * HLV POS IndexedDB Recovery (Aggressive Mode)
 * Odoo 18 POS crashes if it tries to open a transaction on a missing store.
 * This script patches the browser's IDBDatabase to catch this error and clear the cache.
 */

const forceReset = () => {
    console.error("[HLV POS FIX] Forcing POS Database Reset...");
    // Clear LocalStorage POS keys
    for (let i = 0; i < browser.localStorage.length; i++) {
        const key = browser.localStorage.key(i);
        if (key && (key.includes("pos") || key.includes("sync"))) {
            browser.localStorage.removeItem(key);
        }
    }

    // Attempt to delete all IndexedDB databases (standard Odoo 18 names)
    if (window.indexedDB.databases) {
        window.indexedDB.databases().then(dbs => {
            dbs.forEach(db => {
                if (db.name && (db.name.includes("pos") || db.name.includes("sync"))) {
                    console.log("[HLV POS FIX] Deleting database:", db.name);
                    window.indexedDB.deleteDatabase(db.name);
                }
            });
        });
    } else {
        window.indexedDB.deleteDatabase("pos-db");
    }

    // Direct reload after a short delay
    setTimeout(() => {
        browser.location.reload();
    }, 500);
};

// 1. Patch IDBDatabase.prototype.transaction
// This catch the error EXACTLY where it's happening in the stack trace
const originalTransaction = IDBDatabase.prototype.transaction;
IDBDatabase.prototype.transaction = function (storeNames) {
    try {
        return originalTransaction.apply(this, arguments);
    } catch (e) {
        if (e.name === "NotFoundError" || e.message.includes("object store")) {
            console.error("[HLV POS FIX] Transaction failed - missing store:", storeNames);
            forceReset();
            throw e; // Still throw to stop execution, but reset is triggered
        }
        throw e;
    }
};

// 2. Global listener as secondary safety
window.addEventListener("unhandledrejection", (event) => {
    const error = event.reason;
    if (error && error.name === "NotFoundError" && (error.message.includes("object store") || error.message.includes("transaction"))) {
        forceReset();
    }
});

console.log("[HLV POS FIX] Aggressive Safeguard Active.");
