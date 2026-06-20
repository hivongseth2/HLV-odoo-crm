/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

export const loyaltyRewardNotificationService = {
    dependencies: ["action", "bus_service", "notification"],

    start(env, { action, bus_service, notification }) {
        bus_service.subscribe("hlv_loyalty_reward_notification", (payload) => {
            const buttons = [];
            if (payload.action) {
                buttons.push({
                    name: _t("Mở yêu cầu"),
                    primary: true,
                    onClick: () => action.doAction(payload.action),
                });
            }

            notification.add(payload.message || "", {
                title: payload.title || _t("Loyalty"),
                type: payload.type || "info",
                sticky: payload.sticky ?? true,
                buttons,
            });
        });
    },
};

registry.category("services").add(
    "hlv_loyalty.reward_notifications",
    loyaltyRewardNotificationService
);
