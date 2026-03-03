/** @odoo-module **/
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

patch(KanbanController.prototype, {
    setup() {
        super.setup(...arguments);
        this.actionService = useService("action");
        this.orm = useService("orm");
    },

    get isDeliveryScheduleLine() {
        return this.props.resModel === "delivery.schedule.line";
    },

    async onRefreshCleanup() {
        // Gọi action_refresh_unassigned trên tất cả records
        const action = await this.orm.call(
            "delivery.schedule.line",
            "action_refresh_unassigned",
            [[]],
        );
        if (action) {
            this.actionService.doAction(action);
        }
    },

    async onTagAssign() {
        const action = await this.orm.call(
            "delivery.schedule.line",
            "action_auto_assign_by_tags",
            [[]],
        );
        if (action) {
            this.actionService.doAction(action);
        }
    },
});
