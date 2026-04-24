/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ActionMenus } from "@web/search/action_menus/action_menus";

patch(ActionMenus.prototype, {
    async loadAvailablePrintItems() {
        const printItems = await super.loadAvailablePrintItems();
        
        const activeIds = this.props.getActiveIds();
        const resModel = this.props.resModel;

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
            // FIX: Truyền chính xác resModel vào mảng args và KHÔNG truyền gì thêm vào args
            // Odoo sẽ map [resModel] tương ứng với tham số model_name của Python
            const bindings = await this.orm.call(
                "ir.actions.actions",
                "get_bindings",
                [resModel], 
                { context: context }
            );

            if (!bindings || !bindings.report) {
                return printItems;
            }

            const allowedReports = bindings.report;
            const allowedIds = new Set(
                allowedReports.map((r) => (typeof r === "object" ? r.id : r))
            );

            return printItems.filter((item) => allowedIds.has(item.id));
        } catch (error) {
            // Log lỗi ra console để debug nếu vẫn tạch
            console.error("Lỗi filter báo cáo:", error);
            return printItems;
        }
    },
});