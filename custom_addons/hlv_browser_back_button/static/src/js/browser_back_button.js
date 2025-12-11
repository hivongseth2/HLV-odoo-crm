/** @odoo-module */

/**
 * HLV Browser Back Button
 * 
 * Thay đổi hành vi của nút ứng dụng (app button) trong Odoo:
 * - CHỈ khi đang ở trong view chi tiết (có breadcrumb .o_back_button)
 * - Sử dụng actionService.restore() để quay về trang trước với filters được giữ nguyên
 * 
 * Approach: Kết hợp popstate listener với actionService.restore()
 */

import { actionService } from "@web/webclient/actions/action_service";
import { patch } from "@web/core/utils/patch";
import { browser } from "@web/core/browser/browser";

// Biến global để lưu reference đến action service instance
let _actionServiceInstance = null;

// Patch actionService để lấy reference và setup popstate listener
patch(actionService, {
    start(env) {
        // Gọi hàm start gốc để lấy service instance
        const service = super.start(env);

        // Lưu reference để sử dụng trong event handlers
        _actionServiceInstance = service;

        // Định nghĩa hàm xử lý popstate event
        const onPopState = async (ev) => {
            console.log('[HLV] Popstate detected - using actionService.restore()');
            try {
                // restore() sẽ lấy controller trước đó từ stack và hiển thị
                // Giữ nguyên filters, scroll position, etc.
                await service.restore();
            } catch (error) {
                console.debug("[HLV] Cannot restore state:", error);
            }
        };

        // Gắn sự kiện lắng nghe popstate
        browser.addEventListener("popstate", onPopState);

        console.log('[HLV] Browser Back Button: ActionService patched');

        return service;
    }
});

// Kiểm tra xem có đang ở trong detail view không
function isInDetailView() {
    return document.querySelector('.o_back_button') !== null;
}

// Hàm để trigger back navigation sử dụng history.back()
// Popstate listener sẽ bắt event này và gọi restore()
function triggerBackNavigation() {
    if (_actionServiceInstance) {
        // Sử dụng history.back() để trigger popstate event
        // Popstate handler sẽ gọi actionService.restore()
        window.history.back();
    } else {
        console.warn('[HLV] ActionService not available');
        window.history.back();
    }
}

// Hàm thay đổi behavior của nút ứng dụng
function modifyAppButton(appButton) {
    if (!appButton) return;

    if (!isInDetailView()) {
        return;
    }

    if (appButton.dataset.hlvModified === 'true') return;

    appButton.dataset.hlvModified = 'true';

    // Clone để remove OWL bindings
    const newButton = appButton.cloneNode(true);

    newButton.addEventListener('click', function (ev) {
        if (!isInDetailView()) {
            return true;
        }

        ev.preventDefault();
        ev.stopPropagation();
        ev.stopImmediatePropagation();

        console.log('[HLV] App button clicked - triggering back navigation');
        triggerBackNavigation();

        return false;
    }, true);

    newButton.addEventListener('mousedown', function (ev) {
        if (isInDetailView()) {
            ev.stopPropagation();
        }
    }, true);

    if (appButton.parentNode) {
        appButton.parentNode.replaceChild(newButton, appButton);
        console.log('[HLV] Modified app button for detail view');
    }
}

// Scan và modify nút ứng dụng
function scanAndModifyAppButtons() {
    if (!isInDetailView()) {
        return;
    }

    const appButtons = document.querySelectorAll('.o_menu_toggle:not([data-hlv-modified="true"])');
    appButtons.forEach(modifyAppButton);
}

// Khởi tạo MutationObserver
function initObserver() {
    const observer = new MutationObserver(() => {
        setTimeout(scanAndModifyAppButtons, 200);
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true
    });
}

// Khởi tạo module
function init() {
    scanAndModifyAppButtons();
    initObserver();
    setInterval(scanAndModifyAppButtons, 2000);
    console.log('[HLV] Browser Back Button module initialized');
}

// Khởi tạo sau một chút delay để đảm bảo actionService đã được patch
setTimeout(init, 500);

console.log('[HLV] Browser Back Button module loaded');
