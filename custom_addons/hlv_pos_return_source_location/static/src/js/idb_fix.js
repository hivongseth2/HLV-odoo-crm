/** @odoo-module **/

/**
 * HLV POS IndexedDB Recovery (Simple & Direct)
 * Intercepts the "NotFoundError" and nukes the browser database to fix Odoo 18 sync issues.
 */

const forceReset = () => {
    console.error("[HLV POS FIX] Starting Emergency Reset...");

    // 1. Clear LocalStorage
    localStorage.clear();

    // 2. Delete the main POS database
    const req = window.indexedDB.deleteDatabase("pos-db");

    req.onsuccess = () => {
        console.log("[HLV POS FIX] Database deleted. Reloading...");
        window.location.reload();
    };

    req.onerror = () => {
        console.error("[HLV POS FIX] Could not delete DB via request, forcing reload.");
        window.location.reload();
    };

    // Fallback reload
    setTimeout(() => window.location.reload(), 1000);
};

// Patch the failing method
const originalTransaction = IDBDatabase.prototype.transaction;
IDBDatabase.prototype.transaction = function (storeNames) {
    try {
        return originalTransaction.apply(this, arguments);
    } catch (e) {
        if (e.name === "NotFoundError" || e.message.includes("object store")) {
            forceReset();
            throw e;
        }
        throw e;
    }
};

window.addEventListener("unhandledrejection", (event) => {
    if (event.reason && event.reason.name === "NotFoundError") {
        forceReset();
    }
});

console.log("[HLV POS FIX] Simple Safeguard Active.");
