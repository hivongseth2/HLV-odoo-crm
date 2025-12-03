/** @odoo-module */

// SỬA ĐỔI QUAN TRỌNG:
// 1. Dùng đường dẫn "@stock_barcode/main_component" (bỏ chữ components)
// 2. Nếu import { MainComponent } vẫn lỗi, hãy thử import MainComponent (không ngoặc)
import { MainComponent } from "@stock_barcode/main_component";
import { patch } from "@web/core/utils/patch";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

patch(MainComponent.prototype, {
    async exit() {
        const barcodeModel = this.env.model;
        let needWarning = false;

        // Logic kiểm tra điều kiện
        if (barcodeModel && barcodeModel.resModel === 'stock.picking' && barcodeModel.record) {
            const state = barcodeModel.record.state;
            const pickingTypeCode = barcodeModel.record.picking_type_code;

            // Nếu là phiếu Internal/Outgoing và đang ở trạng thái 'assigned' (Sẵn sàng)
            if (['internal', 'outgoing'].includes(pickingTypeCode) && state === 'assigned') {
                needWarning = true;
            }
        }

        if (needWarning) {
            // Lưu reference hàm exit gốc
            const doExit = () => super.exit();

            this.env.services.dialog.add(ConfirmationDialog, {
                title: _t("Cảnh báo thoát"),
                body: _t("Phiếu đang giữ hàng (Reserved). Nếu thoát, hàng sẽ bị treo.\nBạn có chắc muốn thoát?"),
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
            return super.exit();
        }
    }
});