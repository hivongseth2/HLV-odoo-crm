/** @odoo-module **/

/**
 * suppress_backorder_notification.js
 *
 * Mục đích: Ẩn thông báo "Đơn hàng tách kiện sau đã được tạo" trong app Barcode.
 *
 * Nguyên nhân lỗi gốc (Frontend đè Backend):
 *   Khi validate phiếu với số lượng thiếu, hệ thống tạo phiếu back-order.
 *   Popup thông báo hiển thị link dẫn thẳng đến phiếu tách kiện mới.
 *   Nếu người dùng click link đó, app Barcode điều hướng sang phiếu mới
 *   nhưng vẫn giữ nguyên `currentLocation` (vị trí quét cũ, đã hết hàng).
 *   JS sẽ ghi đè vị trí đó vào các dòng stock.move.line của phiếu mới
 *   => phiếu bị gán sai vị trí, trạng thái hiển thị "Sẵn sàng" nhưng không có hàng.
 *
 * Giải pháp:
 *   1. Ẩn ngay thông báo khi nó xuất hiện trong DOM (MutationObserver).
 *   2. Patch BarcodeModel để reset currentLocation khi load phiếu mới.
 */

import { patch } from "@web/core/utils/patch";
import BarcodeModel from "@stock_barcode/models/barcode_model";

// ---------------------------------------------------------------------------
// PHẦN 1: Ẩn thông báo tách kiện qua MutationObserver
// ---------------------------------------------------------------------------

const HLV_BACKORDER_KEYWORDS = ['tách kiện'];

function _hlvShouldSuppressNotification(el) {
    const text = el.textContent || '';
    return HLV_BACKORDER_KEYWORDS.some((kw) => text.includes(kw));
}

function _hlvWatchNotificationManager(manager) {
    if (manager.__hlvBackorderSuppressorAttached) return;
    manager.__hlvBackorderSuppressorAttached = true;

    new MutationObserver((mutations) => {
        for (const { addedNodes } of mutations) {
            for (const node of addedNodes) {
                if (node.nodeType !== 1) continue;
                if (_hlvShouldSuppressNotification(node)) {
                    node.style.setProperty('display', 'none', 'important');
                    // Remove from DOM on next tick to avoid OWL reconciliation errors
                    setTimeout(() => {
                        if (node.isConnected) node.remove();
                    }, 0);
                }
            }
        }
    }).observe(manager, { childList: true });
}

function _hlvSetupBackorderSuppressor() {
    // Watch for the notification manager to be mounted (it's rendered lazily by Odoo)
    new MutationObserver((mutations) => {
        for (const { addedNodes } of mutations) {
            for (const node of addedNodes) {
                if (node.nodeType !== 1) continue;
                // Direct match (notification manager itself was added)
                if (node.classList?.contains('o_notification_manager')) {
                    _hlvWatchNotificationManager(node);
                }
                // Deep match (notification manager inside a newly added subtree)
                const nested = node.querySelector?.('.o_notification_manager');
                if (nested) _hlvWatchNotificationManager(nested);
            }
        }
    }).observe(document.body, { childList: true, subtree: true });

    // Handle case where notification manager is already in the DOM
    document.querySelectorAll('.o_notification_manager').forEach(_hlvWatchNotificationManager);
}

// Start suppressor at module load time (body is available by this point
// because @odoo-module JS is loaded after the DOM is bootstrapped)
try {
    _hlvSetupBackorderSuppressor();
} catch (e) {
    console.warn('[HLV] suppress_backorder_notification: failed to setup observer', e);
}

// ---------------------------------------------------------------------------
// PHẦN 2: Patch BarcodeModel – reset currentLocation khi load phiếu mới
// (Failsafe: nếu người dùng vẫn mở được phiếu tách, location sẽ không bị đè)
// ---------------------------------------------------------------------------

const _hlvLastPickingId = { value: null };

if (BarcodeModel) {
    patch(BarcodeModel.prototype, {
        async load() {
            const result = await super.load(...arguments);
            try {
                const newPickingId = this.resId || (this.record && this.record.id);
                if (newPickingId && newPickingId !== _hlvLastPickingId.value) {
                    // Đây là một phiếu khác với phiếu đang làm việc trước đó
                    // => Xóa vị trí hiện tại để tránh kế thừa sai
                    if (_hlvLastPickingId.value !== null && this.location) {
                        // Chỉ reset khi chuyển sang phiếu mới (không phải lần đầu mở app)
                        this.location = null;
                    }
                    _hlvLastPickingId.value = newPickingId;
                }
            } catch (e) {
                // Không làm gián đoạn luồng barcode nếu patch lỗi
            }
            return result;
        },
    });
}
