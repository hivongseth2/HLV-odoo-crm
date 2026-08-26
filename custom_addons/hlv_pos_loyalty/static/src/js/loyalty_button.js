/** @odoo-module */
import { Component, useState } from "@odoo/owl";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class LoyaltyScanButton extends Component {
    static template = "hlv_pos_loyalty.LoyaltyScanButton";

    setup() {
        this.pos = usePos();
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            loading: false,
        });
    }

    get currentOrder() {
        return this.pos.get_order();
    }

    get loyaltyAccount() {
        return this.currentOrder?.loyalty_account || null;
    }

    async onClickScan() {
        const phone = prompt(_t("Quét hoặc nhập Số điện thoại / Mã thành viên Loyalty:"));
        if (!phone) return;

        this.state.loading = true;
        try {
            const partner = this.currentOrder.get_partner();
            const result = await this.orm.call(
                "hlv.loyalty.portal.account",
                "pos_lookup_or_create_account",
                [phone.trim(), partner ? partner.id : false]
            );

            if (result && result.id) {
                this.currentOrder.loyalty_account_id = result.id;
                this.currentOrder.loyalty_account = result;
                this.notification.add(
                    _t(`Đã áp dụng thành viên: ${result.name} (${result.ranking_points} điểm)`),
                    { type: "success" }
                );
            }
        } catch (error) {
            this.notification.add(_t("Không tìm thấy hoặc không tạo được tài khoản Loyalty."), {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
        }
    }

    onRemoveLoyalty() {
        if (this.currentOrder) {
            this.currentOrder.loyalty_account_id = null;
            this.currentOrder.loyalty_account = null;
        }
    }
}

ProductScreen.addControlButton({
    component: LoyaltyScanButton,
    condition: () => true,
});
