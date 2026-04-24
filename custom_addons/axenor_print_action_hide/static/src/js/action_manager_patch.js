/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ActionMenus } from "@web/search/action_menus/action_menus";

patch(ActionMenus.prototype, {
    async loadAvailablePrintItems() {
        // 1. Gọi hàm gốc để lấy danh sách print items ban đầu
        const printItems = await super.loadAvailablePrintItems();
        
        const activeIds = this.props.getActiveIds();
        const resModel = this.props.resModel;

        if (activeIds.length > 0 && printItems && printItems.length > 0) {
            const context = {
                ...this.props.context,
                active_ids: activeIds,
                active_id: activeIds[0],
                active_model: resModel,
            };

            // 2. Gọi server để kiểm tra các báo cáo được phép (get_bindings)
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

            // 3. Trả về danh sách đã lọc mà không cần ghi đè this.props
            return printItems.filter((item) => allowedIds.has(item.id));
        }

        return printItems;
    },
});