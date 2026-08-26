/** @odoo-module **/

import { useEffect } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { _t } from "@web/core/l10n/translation";

patch(ProductScreen.prototype, {
    setup() {
        super.setup();
        this.pos = usePos();
        this.orm = useService("orm");
        this.notification = useService("notification");

        useEffect(
            () => {
                this._renderLoyaltyControls();
            },
            () => {
                const order = this.pos.get_order();
                return [order?.loyalty_account_id, order?.loyalty_account?.name];
            }
        );
    },

    _renderLoyaltyControls() {
        const render = () => {
            const order = this.pos.get_order();
            if (!order) return;

            // Tìm vị trí đặt nút trong khu vực actionpad / control-buttons của POS ProductScreen
            const container = document.querySelector(".actionpad") ||
                              document.querySelector(".set-partner-button")?.parentElement ||
                              document.querySelector(".pads") ||
                              document.querySelector(".product-screen .leftpane");

            if (!container) return;

            let loyaltyWrap = document.querySelector(".hlv-pos-loyalty-container");
            if (!loyaltyWrap) {
                loyaltyWrap = document.createElement("div");
                loyaltyWrap.className = "hlv-pos-loyalty-container d-flex align-items-center my-1";
                container.prepend(loyaltyWrap);
            }

            const loyaltyAccount = order.loyalty_account;

            if (!loyaltyAccount) {
                loyaltyWrap.innerHTML = `
                    <button type="button" class="btn btn-secondary loyalty-scan-btn d-flex align-items-center gap-1 w-100 py-2 justify-content-center border-primary text-primary fw-bold" style="border: 1.5px solid #1779b4 !important;">
                        <i class="fa fa-qrcode fa-lg"></i>
                        <span>Tích điểm Loyalty</span>
                    </button>
                `;
                const btn = loyaltyWrap.querySelector("button");
                if (btn) {
                    btn.onclick = (ev) => {
                        ev.preventDefault();
                        this._onLoyaltyScanClick();
                    };
                }
            } else {
                loyaltyWrap.innerHTML = `
                    <div class="loyalty-member-badge d-flex align-items-center justify-content-between p-2 rounded w-100 bg-success-subtle border border-success">
                        <div class="d-flex align-items-center gap-2">
                            <i class="fa fa-star text-warning fa-lg"></i>
                            <div class="d-flex flex-column text-start">
                                <strong class="text-success" style="font-size: 13px;">${loyaltyAccount.name}</strong>
                                <small class="text-muted" style="font-size: 11px;">${loyaltyAccount.tier_name || 'Thành viên'} • ${loyaltyAccount.ranking_points || 0} điểm</small>
                            </div>
                        </div>
                        <button type="button" class="btn btn-sm btn-link text-danger p-0 ms-2 remove-loyalty-btn" title="Hủy áp dụng Loyalty" style="text-decoration: none; font-weight: bold; font-size: 16px;">✕</button>
                    </div>
                `;
                const removeBtn = loyaltyWrap.querySelector(".remove-loyalty-btn");
                if (removeBtn) {
                    removeBtn.onclick = (ev) => {
                        ev.preventDefault();
                        order.loyalty_account_id = null;
                        order.loyalty_account = null;
                        this.notification.add(_t("Đã gỡ tài khoản Loyalty khỏi đơn hàng."), { type: "info" });
                        this._renderLoyaltyControls();
                    };
                }
            }
        };

        render();
        setTimeout(render, 100);
        setTimeout(render, 500);
        setTimeout(render, 1000);
    },

    async _onLoyaltyScanClick() {
        const phone = prompt(_t("Quét mã Barcode/QR trên App hoặc nhập Số điện thoại:"));
        if (!phone || !phone.trim()) return;

        const order = this.pos.get_order();
        if (!order) return;

        try {
            const partner = order.get_partner();
            const result = await this.orm.call(
                "hlv.loyalty.portal.account",
                "pos_lookup_or_create_account",
                [phone.trim(), partner ? partner.id : false]
            );

            if (result && result.id) {
                order.loyalty_account_id = result.id;
                order.loyalty_account = result;
                this.notification.add(
                    _t(`Đã áp dụng thành viên: ${result.name} (${result.ranking_points} điểm)`),
                    { type: "success" }
                );
                this._renderLoyaltyControls();
            }
        } catch (error) {
            this.notification.add(
                _t("Không tìm thấy hoặc không tạo được tài khoản Loyalty: ") + (error?.data?.message || error?.message || ""),
                { type: "danger" }
            );
        }
    },
});
