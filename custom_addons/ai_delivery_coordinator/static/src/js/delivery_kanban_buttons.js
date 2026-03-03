/** @odoo-module **/
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { useService } from "@web/core/utils/hooks";

export class DeliveryKanbanController extends KanbanController {
    setup() {
        super.setup();
        this.actionService = useService("action");
        this.orm = useService("orm");
    }

    async onRefreshCleanup() {
        const action = await this.orm.call(
            "delivery.schedule.line",
            "action_refresh_unassigned",
            [[]],
        );
        if (action) {
            await this.actionService.doAction(action);
        }
    }

    async onTagAssign() {
        const action = await this.orm.call(
            "delivery.schedule.line",
            "action_auto_assign_by_tags",
            [[]],
        );
        if (action) {
            await this.actionService.doAction(action);
        }
    }
}

export const deliveryKanbanView = {
    ...kanbanView,
    Controller: DeliveryKanbanController,
    buttonTemplate: "ai_delivery_coordinator.DeliveryKanbanButtons",
};

registry.category("views").add("delivery_kanban", deliveryKanbanView);
