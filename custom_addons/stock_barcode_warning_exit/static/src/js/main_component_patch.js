/** @odoo-module */

// QUAN TRỌNG: 
// 1. Dùng đường dẫn cũ: "@stock_barcode/components/main"
// 2. Bỏ dấu ngoặc nhọn {} để import theo kiểu Default.
import MainComponent from "@stock_barcode/components/main";
import { patch } from "@web/core/utils/patch";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

// Kiểm tra an toàn: Nếu MainComponent thực sự load được mới patch
if (MainComponent) {
    patch(MainComponent.prototype, {
        async exit() {
            const barcodeModel = this.env.model;
            let needWarning = false;

            // Kiểm tra điều kiện
            if (barcodeModel && barcodeModel.resModel === 'stock.picking' && barcodeModel.record) {
                const state = barcodeModel.record.state;
                const pickingTypeCode = barcodeModel.record.picking_type_code;

                // Điều kiện: Phiếu Internal/Outgoing và đang giữ hàng (assigned)
                if (['internal', 'outgoing'].includes(pickingTypeCode) && state === 'assigned') {
                    needWarning = true;
                }
            }

            if (needWarning) {
                // Lưu tham chiếu hàm gốc
                const doExit = () => super.exit();

                this.env.services.dialog.add(ConfirmationDialog, {
                    title: _t("Cảnh báo thoát"),
                    body: _t("Phiếu đang giữ hàng (Reserved). Nếu thoát ngay, hàng sẽ bị treo.\n\nBạn có chắc chắn muốn thoát?"),
                    confirmLabel: _t("Vẫn thoát"),
                    cancelLabel: _t("Ở lại"),
                    confirm: () => {
                        doExit();
                    },
                    cancel: () => {
                        // Không làm gì
                    }
                });
            } else {
                // Không cảnh báo -> Thoát luôn
                return super.exit();
            }
        }
    });
} else {
    console.error("Stock Barcode Warning: Không thể tìm thấy MainComponent tại @stock_barcode/components/main");
}