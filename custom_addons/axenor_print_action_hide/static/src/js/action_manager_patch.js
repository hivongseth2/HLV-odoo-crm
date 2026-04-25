/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ActionMenus } from "@web/search/action_menus/action_menus";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

patch(ActionMenus.prototype, {
    async loadAvailablePrintItems() {
        const activeIds = this.props.getActiveIds();
        const resModel = this.props.resModel;

        const originalItems = await super.loadAvailablePrintItems();

        if (!activeIds.length) {
            return originalItems;
        }

        const context = {
            ...this.props.context,
            active_ids: activeIds,
            active_id: activeIds[0],
            active_model: resModel,
        };

        let bindings;
        bindings = await this.orm.call(
                "ir.actions.actions",
                "get_bindings",
                [resModel],
                { context: context }
            );
        const allowedReports = bindings.report || bindings.reports || [];
        const allowedIds = new Set(
            allowedReports.map((r) => (typeof r === "object" ? r.id : r))
        );

        return originalItems.filter((item) => {
            if (!item.action?.id) return true;
            return allowedIds.has(item.action.id);
        });
    },
});