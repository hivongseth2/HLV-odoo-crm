/** @odoo-module */

/**
 * HLV Browser Back Button
 * 
 * Replaces the default behavior of the App Button (top-left) in detail views.
 * Instead of going to the App Menu, it acts as a "Back" button (Action Restore).
 * 
 * APPROACH:
 * - Uses a global 'capture' phase click listener to intercept the event BEFORE Odoo's native handlers.
 * - Checks if we are in a detail view (breadcrumbs exist).
 * - Calls actionService.restore() to go back to the previous controller state (preserving filters).
 * - Non-destructive: Does NOT modify/replace DOM nodes, avoiding OWL freezing/crashes.
 */

import { actionService } from "@web/webclient/actions/action_service";
import { patch } from "@web/core/utils/patch";

// Global reference to the action service
let _actionServiceInstance = null;

// Patch actionService to capture the instance
patch(actionService, {
    start(env) {
        const service = super.start(env);
        _actionServiceInstance = service;
        console.log('[HLV] Browser Back Button: ActionService instance captured');
        return service;
    }
});

// Helper: Check if we are inside the App Button (.o_menu_toggle or its children)
function isAppButtonClicked(target) {
    return target.closest('.o_menu_toggle') !== null;
}

// Helper: Check if we are in a Detail View (Breadcrumbs exist)
function isInDetailView() {
    // .o_back_button indicates we are deep in a stack (standard Odoo breadcrumb)
    // The main app menu usually doesn't have this or only has the root item.
    return document.querySelector('.o_back_button') !== null;
}

/**
 * Global Capture Click Handler
 * Intercepts clicks on the App Button when in Detail View.
 */
function onGlobalClick(ev) {
    // 1. Must be the App Button
    if (!isAppButtonClicked(ev.target)) {
        return;
    }

    // 2. Must be in Detail View
    if (!isInDetailView()) {
        return;
    }

    // 3. Must have the Action Service ready
    if (!_actionServiceInstance) {
        console.warn('[HLV] ActionService not ready yet.');
        return;
    }

    // 4. Intercept!
    // Stop the event from reaching Odoo's native handlers (which would toggle the menu)
    ev.preventDefault();
    ev.stopPropagation();
    ev.stopImmediatePropagation();

    console.log('[HLV] App Button Click intercepted -> Restoring previous action state');

    // 5. Restore State (Go Back)
    _actionServiceInstance.restore().catch(error => {
        console.error("[HLV] Failed to restore action state:", error);
    });
}

// Add the listener to the document with { capture: true }
// This ensures we run BEFORE any bubbling listeners attached by OWL/Odoo
document.addEventListener("click", onGlobalClick, { capture: true });

console.log('[HLV] Browser Back Button: Safe Global Listener registered');
