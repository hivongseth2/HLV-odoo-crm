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
        // Check both 'product' (storable) and 'consu' (consumable)
        const storableLines = orderLines.filter(l => {
            const p = l.get_product();
            console.log(`DEBUG: Line product: ${p.display_name}, type: ${p.type}, detailed_type: ${p.detailed_type}`);
            return p.type === 'product' || p.detailed_type === 'product' || p.type === 'consu' || p.detailed_type === 'consu';
        });

        console.log("DEBUG: storableLines found count:", storableLines.length);

        if (storableLines.length > 0) {
            const productIds = storableLines.map(l => l.get_product().id);
            const warehouseId = this.pos.config.warehouse_id ? (Array.isArray(this.pos.config.warehouse_id) ? this.pos.config.warehouse_id[0] : this.pos.config.warehouse_id) : false;

            console.log("DEBUG: warehouseId identified:", warehouseId);

            if (warehouseId) {
                try {
                    const stockData = await this.env.services.orm.call(
                        'pos.session',
                        'get_products_stock',
                        [productIds, warehouseId]
                    );

                    console.log("DEBUG: stockData received:", stockData);

                    for (const line of storableLines) {
                        const product = line.get_product();
                        const qtyRequested = line.get_quantity();
                        const qtyAvailable = stockData[product.id] || 0;

                        console.log(`DEBUG: Checking ${product.display_name}: Requested ${qtyRequested}, Available ${qtyAvailable}`);

                        if (qtyRequested > qtyAvailable) {
                            console.log(`DEBUG: BLOCKING validation for ${product.display_name}`);
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
                    console.error("DEBUG: Error during stock validation RPC:", error);
                    // Fallback: allow validation if RPC fails to avoid blocking the shop completely
                }
            } else {
                console.warn("DEBUG: warehouseId not found in pos.config");
            }
        }

        await super.validateOrder(isForceValidate);
    }
});
