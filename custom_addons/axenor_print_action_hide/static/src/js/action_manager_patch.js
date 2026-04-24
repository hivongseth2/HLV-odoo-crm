/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ActionMenus } from "@web/search/action_menus/action_menus";

patch(ActionMenus.prototype, {
    async loadAvailablePrintItems() {
        const printItems = await super.loadAvailablePrintItems();
        
        const activeIds = this.props.getActiveIds();
        const resModel = this.props.resModel;

        // Nếu không có model hoặc không có item nào để in thì thôi, trả về luôn
        if (!resModel || !activeIds.length || !printItems?.length) {
            return printItems;
        }

        const context = {
            ...this.props.context,
            active_ids: activeIds,
            active_id: activeIds[0],
            active_model: resModel,
        };

        try {
            const bindings = await this.orm.call(
                "ir.actions.actions",
                "get_bindings",
                [resModel], // Tham số model_name
                { context: context }
            );

            const allowedReports = bindings.report || [];
            const allowedIds = new Set(
                allowedReports.map((r) => (typeof r === "object" ? r.id : r))
            );

            return printItems.filter((item) => allowedIds.has(item.id));
        } catch (error) {
            console.error("Lỗi khi lọc danh sách in:", error);
            return printItems; // Nếu lỗi thì cho hiện hết, đừng để crash giao diện
        }
    },
});