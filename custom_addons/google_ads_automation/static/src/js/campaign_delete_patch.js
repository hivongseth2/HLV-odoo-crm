/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";
import { FormController } from "@web/views/form/form_controller";

/**
 * Patch ListController to intercept bulk deletion from the Action menu.
 */
patch(ListController.prototype, {
    async onDeleteSelectedRecords() {
        if (this.props.resModel === "google.ads.campaign") {
            const resIds = await this.getSelectedResIds();
            if (resIds.length > 0) {
                // Trigger our custom wizard instead of standard confirmation
                return this.actionService.doAction("google_ads_automation.action_google_ads_campaign_remove_wizard", {
                    additionalContext: {
                        default_campaign_ids: [[6, 0, resIds]],
                    },
                });
            }
        }
        return super.onDeleteSelectedRecords(...arguments);
    },
});

/**
 * Patch FormController to intercept deletion from the trash can icon/button.
 */
patch(FormController.prototype, {
    async onDeleteRecord() {
        if (this.props.resModel === "google.ads.campaign") {
            const resId = this.model.root.resId;
            if (resId) {
                // Trigger our custom wizard
                return this.actionService.doAction("google_ads_automation.action_google_ads_campaign_remove_wizard", {
                    additionalContext: {
                        default_campaign_ids: [[6, 0, [resId]]],
                    },
                });
            }
        }
        return super.onDeleteRecord(...arguments);
    },
});
