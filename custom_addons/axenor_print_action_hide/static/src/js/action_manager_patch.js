/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ActionMenus } from "@web/search/action_menus/action_menus";

patch(ActionMenus.prototype, {
    async loadAvailablePrintItems() {
        const activeIds = this.props.getActiveIds();
        const resModel = this.props.resModel;
        
        console.log("=== axenor patch loadAvailablePrintItems ===");
        console.log("resModel:", resModel);
        console.log("activeIds:", activeIds);
        console.log("props.items.print:", this.props.items.print);

        const originalItems = await super.loadAvailablePrintItems();
        console.log("originalItems:", originalItems);

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
        try {
            bindings = await this.orm.call(
                "ir.actions.actions",
                "get_bindings",
                [resModel],
                { context }
            );
            console.log("bindings:", bindings);
        } catch (e) {
            console.warn("axenor: get_bindings failed", e);
            return originalItems;
        }

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