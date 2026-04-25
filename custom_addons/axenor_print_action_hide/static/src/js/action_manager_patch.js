/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ActionMenus } from "@web/search/action_menus/action_menus";

patch(ActionMenus.prototype, {
    async loadAvailablePrintItems() {
        // Gọi super() trước để lấy danh sách gốc
        const originalItems = await super.loadAvailablePrintItems();
        
        const activeIds = this.props.getActiveIds();
        const resModel = this.props.resModel;

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
        } catch (e) {
            console.warn("axenor: get_bindings failed", e);
            return originalItems;
        }

        const allowedReports = bindings.report || bindings.reports || [];
        const allowedIds = new Set(
            allowedReports.map((r) => (typeof r === "object" ? r.id : r))
        );

        // Filter items trả về từ super()
        return originalItems.filter((item) => {
            // Giữ lại item không phải report (vd: "No report available")
            if (!item.action?.id) return true;
            return allowedIds.has(item.action.id);
        });
    },
});