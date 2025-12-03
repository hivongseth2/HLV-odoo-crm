/** @odoo-module */

import { MainComponent } from "@stock_barcode/components/main";
import { patch } from "@web/core/utils/patch";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

patch(MainComponent.prototype, {
    /**
     * Ghi đè hàm exit (hàm được gọi khi nhấn nút Back/Thoát trên giao diện)
     */
    async exit() {
        // Lấy thông tin phiếu hiện tại
        const record = this.env.model.root;

        // Điều kiện kích hoạt cảnh báo:
        // 1. Phải đang ở trong một phiếu (record tồn tại)
        // 2. Phiếu phải là phiếu xuất hoặc chuyển nội bộ (tránh làm phiền khi nhập hàng)
        // 3. Trạng thái phiếu là 'assigned' (Sẵn sàng - đang giữ hàng) hoặc 'processing'

        // Lưu ý: Tùy version Odoo mà cách truy cập biến có thể khác nhau một chút.
        // Đây là code chuẩn cho Odoo 16/17.

        let needWarning = false;

        if (record && record.resModel === 'stock.picking') {
            const state = record.data.state;
            const pickingTypeCode = record.data.picking_type_code; // internal, outgoing, incoming

            // Chỉ cảnh báo với phiếu Chuyển nội bộ (internal) hoặc Xuất hàng (outgoing)
            // Đang ở trạng thái Sẵn sàng (assigned)
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
                    // Nếu người dùng cố tình muốn thoát, gọi hàm gốc
                    super.exit();
                },
                cancel: () => {
                    // Không làm gì cả, giữ người dùng ở lại màn hình
                }
            });
        } else {
            // Nếu không thỏa điều kiện cảnh báo thì thoát bình thường
            super.exit();
        }
    }
});