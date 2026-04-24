/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ActionMenus } from "@web/search/action_menus/action_menus";

patch(ActionMenus.prototype, {
    async loadAvailablePrintItems() {
        const activeIds = this.props.getActiveIds();
        const resModel = this.props.resModel;

        // Gọi get_bindings lại với active_ids đúng để filter operation_type
        if (activeIds.length > 0) {
            const context = {
                ...this.props.context,
                active_ids: activeIds,
                active_id: activeIds[0],
                active_model: resModel,
            };

            const bindings = await this.orm.call(
                "ir.actions.actions",
                "get_bindings",
                [resModel],
                { context }
            );

            const allowedReports = bindings.report || [];
            const allowedIds = new Set(
                allowedReports.map((r) => (typeof r === "object" ? r.id : r))
            );

            // Filter lại props.items.print theo allowedIds
            const filteredPrint = (this.props.items.print || []).filter((a) =>
                allowedIds.has(a.id)
            );

            // Tạm thời override items để super() dùng list đã filter
            const originalItems = this.props.items;
            this.props = Object.assign(Object.create(Object.getPrototypeOf(this.props)), this.props, {
                items: { ...originalItems, print: filteredPrint },
            });
        }

        return super.loadAvailablePrintItems();
    },
});