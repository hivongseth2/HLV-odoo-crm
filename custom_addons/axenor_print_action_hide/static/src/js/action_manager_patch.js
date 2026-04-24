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
            // Cách gọi này ép Python phải nhận model_name từ kwargs 
            // nếu nó không tìm thấy trong positional args
            const bindings = await this.orm.call(
                "ir.actions.actions",
                "get_bindings",
                [], // Để trống args
                { 
                    model_name: resModel, // Truyền trực tiếp vào đây
                    context: context 
                }
            );

            const allowedReports = bindings.report || [];
            const allowedIds = new Set(
                allowedReports.map((r) => (typeof r === "object" ? r.id : r))
            );

            return printItems.filter((item) => allowedIds.has(item.id));
        } catch (error) {
            console.error("Lỗi lọc báo cáo:", error);
            return printItems;
        }
    },
});