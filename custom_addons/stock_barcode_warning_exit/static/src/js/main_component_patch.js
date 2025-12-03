/** @odoo-module */

// SỬA LỖI: Đường dẫn import chính xác cho Odoo 17/18
import { MainComponent } from "@stock_barcode/main_component";
import { patch } from "@web/core/utils/patch";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

patch(MainComponent.prototype, {
    /**
     * Ghi đè hàm exit
     */
    async exit() {
        const barcodeModel = this.env.model;
        let needWarning = false;

        // Kiểm tra điều kiện
        if (barcodeModel && barcodeModel.resModel === 'stock.picking' && barcodeModel.record) {
            const state = barcodeModel.record.state;
            const pickingTypeCode = barcodeModel.record.picking_type_code;

            // assigned: Sẵn sàng (đang giữ hàng)
            if (['internal', 'outgoing'].includes(pickingTypeCode) && state === 'assigned') {
                needWarning = true;
            }
        }

        if (needWarning) {
            // Lưu lại tham chiếu đến hàm gốc để gọi trong callback
            const doExit = () => super.exit();

            this.env.services.dialog.add(ConfirmationDialog, {
                title: _t("Cảnh báo thoát"),
                body: _t("Phiếu này đang giữ hàng (Dự trữ). Nếu bạn thoát ngay bây giờ, hàng sẽ bị 'treo' và người khác không thể xử lý.\n\nBạn có chắc chắn muốn thoát không?"),
                confirmLabel: _t("Vẫn thoát"),
                cancelLabel: _t("Ở lại xử lý"),
                confirm: () => {
                    // Gọi hàm gốc đã được bọc lại
                    doExit();
                },
                cancel: () => {
                    // Không làm gì, giữ user ở lại
                }
            });
        } else {
            // Trường hợp bình thường
            return super.exit();
        }
    }
});