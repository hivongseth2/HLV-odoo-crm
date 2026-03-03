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

    /**
     * Get IDs of records where is_selected=True (set via native boolean widget)
     */
    async _getSelectedIds() {
        const records = await this.orm.searchRead(
            "delivery.schedule.line",
            [["is_selected", "=", true]],
            ["id"],
        );
        return records.map((r) => r.id);
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
        const ids = await this._getSelectedIds();
        const action = await this.orm.call(
            "delivery.schedule.line",
            "action_auto_assign_by_tags",
            [ids.length ? ids : []],
        );
        if (action) {
            await this.actionService.doAction(action);
        }
    }

    async onAiAssign() {
        const ids = await this._getSelectedIds();
        const action = await this.orm.call(
            "delivery.schedule.line",
            "action_ai_assign_routes",
            [ids.length ? ids : []],
        );
        if (action) {
            await this.actionService.doAction(action);
        }
    }

    async onCreateTrip() {
        const ids = await this._getSelectedIds();
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "delivery.trip.wizard",
            name: "Tạo Chuyến Giao",
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_selected_line_ids: ids,
            },
        });
    }

    async onClearSelection() {
        await this.orm.call(
            "delivery.schedule.line",
            "action_clear_selection",
            [[]],
        );
        this.actionService.doAction({
            type: "ir.actions.client",
            tag: "soft_reload",
        });
    }
}

export const deliveryKanbanView = {
    ...kanbanView,
    Controller: DeliveryKanbanController,
    buttonTemplate: "ai_delivery_coordinator.DeliveryKanbanButtons",
};

registry.category("views").add("delivery_kanban", deliveryKanbanView);
