/** @odoo-module */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(PaymentScreen.prototype, {
    async validateOrder(isForceValidate) {
        console.log("DEBUG: validateOrder called in patch");
        const partner = this.currentOrder.get_partner();
        console.log("DEBUG: Current partner:", partner);

        if (!partner) {
            console.log("DEBUG: No partner selected, blocking validation");
            this.env.services.notification.add(_t('Vui lòng chọn khách hàng để thanh toán.'), {
                type: 'danger',
                sticky: false,
                title: _t('Yêu cầu khách hàng'),
            });
            return;
        }

        // Stock validation
        const orderLines = this.currentOrder.get_orderlines();
        console.log("DEBUG: Order lines count:", orderLines.length);

        for (const line of orderLines) {
            const product = line.get_product();
            const qtyRequested = line.get_quantity();
            const qtyAvailable = product.qty_available;

            console.log("DEBUG: Product:", product.display_name, "Type:", product.type, "Qty:", qtyRequested, "Avail:", qtyAvailable);

            // alert(`Kiểm tra ${product.display_name}: Loại=${product.type}, Cần=${qtyRequested}, Có=${qtyAvailable}`);

            if (product.type === 'product' || product.type === 'consu') {
                if (qtyAvailable !== undefined && qtyRequested > qtyAvailable) {
                    this.env.services.notification.add(
                        _t('Sản phẩm "%s" không đủ tồn kho (Yêu cầu: %s, Hiện có: %s).',
                            product.display_name, qtyRequested, qtyAvailable), {
                        type: 'danger',
                        sticky: true,
                        title: _t('Lỗi tồn kho'),
                    });
                    // alert(`CHẶN: ${product.display_name} không đủ hàng!`);
                    return;
                }
            }
        }

        await super.validateOrder(isForceValidate);
    }
});
