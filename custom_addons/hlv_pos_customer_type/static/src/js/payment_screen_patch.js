/** @odoo-module */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(PaymentScreen.prototype, {
    async validateOrder(isForceValidate) {
        const order = this.currentOrder;
        const pos = this.pos;
        // Odoo 18 might use different paths. Try multiple common ones.
        const configId = pos.config ? pos.config.id : false;
        const session = pos.pos_session || pos.session || {};
        const sessionId = session.id || pos.pos_session_id || false;

        console.log("-----------------------------------------");
        console.log(`DEBUG IDENTITY: validateOrder triggered`);
        console.log(`DEBUG IDENTITY: Current Order: ${order ? order.name : 'NULL'}`);
        console.log(`DEBUG IDENTITY: Active POS Config ID: ${configId}`);
        console.log(`DEBUG IDENTITY: Active Session ID: ${sessionId}`);

        const partner = order.get_partner();
        if (!partner) {
            this.env.services.notification.add(_t('Vui lòng chọn khách hàng để thanh toán.'), {
                type: 'danger',
                sticky: false,
                title: _t('Yêu cầu khách hàng'),
            });
            return;
        }

        // Stock validation via RPC
        const orderLines = order.get_orderlines();
        const storableLines = orderLines.filter(l => {
            const p = l.get_product();
            return p.type === 'product' || p.type === 'consu';
        });

        if (storableLines.length > 0) {
            const productIds = storableLines.map(l => l.get_product().id);

            console.log(`DEBUG IDENTITY: SENDING RPC - products: [${productIds.join(',')}], session: ${sessionId}, config: ${configId}`);

            try {
                // Pass both sessionId and configId for robust backend lookup
                const stockData = await this.env.services.orm.call(
                    'pos.session',
                    'get_products_stock',
                    [productIds, false, sessionId, configId]
                );

                console.log(`DEBUG IDENTITY: RECEIVED RPC DATA:`, stockData);

                for (const line of storableLines) {
                    const product = line.get_product();
                    const qtyRequested = line.get_quantity();
                    const qtyAvailable = (stockData && stockData[product.id] !== undefined) ? stockData[product.id] : 0;

                    if (qtyRequested > qtyAvailable) {
                        this.env.services.notification.add(
                            _t('Sản phẩm "%s" không đủ tồn kho (Yêu cầu: %s, Hiện có: %s).',
                                product.display_name, qtyRequested, qtyAvailable), {
                            type: 'danger',
                            sticky: true,
                            title: _t('Lỗi tồn kho'),
                        });
                        return; // BLOCK confirmation
                    }
                }
            } catch (error) {
                console.error("DEBUG IDENTITY: RPC FAILED", error);
            }
        }
        console.log("-----------------------------------------");

        await super.validateOrder(isForceValidate);
    }
});
