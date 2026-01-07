/** @odoo-module */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(PaymentScreen.prototype, {
    async validateOrder(isForceValidate) {
        const order = this.currentOrder;
        const pos = this.pos;
        const session = pos.pos_session;
        const config = pos.config;

        console.log("-----------------------------------------");
        console.log(`DEBUG IDENTITY: validateOrder triggered`);
        console.log(`DEBUG IDENTITY: Current Order: ${order ? order.name : 'NULL'} (UID: ${order ? order.uid : 'NULL'})`);
        console.log(`DEBUG IDENTITY: Active POS Config: ${config ? config.name : 'NULL'} (ID: ${config ? config.id : 'NULL'})`);
        console.log(`DEBUG IDENTITY: Active Session ID: ${session ? session.id : 'NULL'}`);
        console.log(`DEBUG IDENTITY: Current User: ${pos.user ? pos.user.name : 'NULL'} (ID: ${pos.user ? pos.user.id : 'NULL'})`);

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
        console.log(`DEBUG IDENTITY: Total Order Lines: ${orderLines.length}`);

        const storableLines = orderLines.filter(l => {
            const p = l.get_product();
            const isStorable = p.type === 'product' || p.type === 'consu';
            console.log(`DEBUG IDENTITY:   - Line Product: ${p.display_name} (ID: ${p.id}), Type: ${p.type}, Qty: ${l.get_quantity()}`);
            return isStorable;
        });

        if (storableLines.length > 0) {
            const productIds = storableLines.map(l => l.get_product().id);
            const sessionId = session ? session.id : false;

            console.log(`DEBUG IDENTITY: SENDING RPC - products: [${productIds.join(',')}], session: ${sessionId}`);

            try {
                const stockData = await this.env.services.orm.call(
                    'pos.session',
                    'get_products_stock',
                    [productIds, false, sessionId]
                );

                console.log(`DEBUG IDENTITY: RECEIVED RPC DATA:`, stockData);

                for (const line of storableLines) {
                    const product = line.get_product();
                    const qtyRequested = line.get_quantity();
                    const qtyAvailable = (stockData && stockData[product.id] !== undefined) ? stockData[product.id] : 0;

                    console.log(`DEBUG IDENTITY: FINAL CHECK - ${product.display_name}: Requested ${qtyRequested}, Available ${qtyAvailable}`);

                    if (qtyRequested > qtyAvailable) {
                        console.log(`DEBUG IDENTITY: !!! BLOCKING !!! - Reason: Insufficient Stock`);
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
        } else {
            console.log(`DEBUG IDENTITY: Skip validation (No storable/consumable products)`);
        }
        console.log("-----------------------------------------");

        await super.validateOrder(isForceValidate);
    }
});
