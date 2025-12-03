/** @odoo-module */

import { MainComponent } from "@stock_barcode/components/main";
import { patch } from "@web/core/utils/patch";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

patch(MainComponent.prototype, {
    /**
     * Ghi đè hàm exit (hàm được gọi khi nhấn nút Back/Thoát trên giao diện App Barcode)
     * Dành cho Odoo 18 Enterprise
     */
    async exit() {
        // Trong Odoo Barcode App, 'this.env.model' là instance của BarcodeModel
        const barcodeModel = this.env.model;

        let needWarning = false;

        // Kiểm tra:
        // 1. Model phải tồn tại
        // 2. Đang thao tác trên model 'stock.picking' (Phiếu kho)
        // 3. Dữ liệu phiếu (record) đã được load
        if (barcodeModel && barcodeModel.resModel === 'stock.picking' && barcodeModel.record) {

            // Truy cập trực tiếp vào data của record trong BarcodeModel
            const state = barcodeModel.record.state;
            const pickingTypeCode = barcodeModel.record.picking_type_code; // internal, outgoing, incoming

            // Điều kiện cảnh báo:
            // - Là phiếu Chuyển nội bộ (internal) hoặc Xuất hàng (outgoing)
            // - Trạng thái là 'assigned' (Sẵn sàng - đang giữ hàng)
            // - (Tùy chọn) Có thể thêm điều kiện: đã quét được ít nhất 1 dòng (để tránh cảnh báo khi vừa mở lên chưa làm gì)
            if (['internal', 'outgoing'].includes(pickingTypeCode) && state === 'assigned') {
                needWarning = true;
            }
        }

        if (needWarning) {
            this.env.services.dialog.add(ConfirmationDialog, {
                title: _t("Cảnh báo thoát"),
                body: _t("Phiếu này đang giữ hàng (Dự trữ). Nếu bạn thoát ngay bây giờ, hàng sẽ bị 'treo' và người khác không thể xử lý.\n\nBạn có chắc chắn muốn thoát không?"),
                confirmLabel: _t("Vẫn thoát"),
                cancelLabel: _t("Ở lại xử lý"),
                confirm: () => {
                    // Nếu người dùng xác nhận thoát, gọi hàm gốc của Odoo
                    super.exit();
                },
                cancel: () => {
                    // Đóng dialog, giữ người dùng ở lại màn hình
                }
            });
        } else {
            // Nếu không thỏa điều kiện cảnh báo thì thoát bình thường
            super.exit();
        }
    }
});