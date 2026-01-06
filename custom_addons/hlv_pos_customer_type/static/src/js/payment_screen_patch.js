/** @odoo-module */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(PaymentScreen.prototype, {
    async validateOrder(isForceValidate) {
        console.log("DEBUG: validateOrder called in patch");
        const partner = this.currentOrder.get_partner();

        if (!partner) {
            this.env.services.notification.add(_t('Vui lòng chọn khách hàng để thanh toán.'), {
                type: 'danger',
                sticky: false,
                title: _t('Yêu cầu khách hàng'),
            });
            return;
        }

        // Stock validation via RPC
        const orderLines = this.currentOrder.get_orderlines();
        const storableLines = orderLines.filter(l => l.get_product().type === 'product' || l.get_product().detailed_type === 'product');

        if (storableLines.length > 0) {
            const productIds = storableLines.map(l => l.get_product().id);
            const warehouseId = this.pos.config.warehouse_id ? (Array.isArray(this.pos.config.warehouse_id) ? this.pos.config.warehouse_id[0] : this.pos.config.warehouse_id) : false;

            if (warehouseId) {
                try {
                    const stockData = await this.env.services.orm.call(
                        'pos.session',
                        'get_products_stock',
                        [productIds, warehouseId]
                    );

                    for (const line of storableLines) {
                        const product = line.get_product();
                        const qtyRequested = line.get_quantity();
                        const qtyAvailable = stockData[product.id] || 0;

                        if (qtyRequested > qtyAvailable) {
                            this.env.services.notification.add(
                                _t('Sản phẩm "%s" không đủ tồn kho (Yêu cầu: %s, Hiện có: %s).',
                                    product.display_name, qtyRequested, qtyAvailable), {
                                type: 'danger',
                                sticky: true,
                                title: _t('Lỗi tồn kho'),
                            });
                            return;
                        }
                    }
                } catch (error) {
                    console.error("Error during stock validation:", error);
                    // Fallback: allow validation if RPC fails to avoid blocking the shop completely
                }
            }
        }

        await super.validateOrder(isForceValidate);
    }
});
