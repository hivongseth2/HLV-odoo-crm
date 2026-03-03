/** @odoo-module **/
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { KanbanRecord } from "@web/views/kanban/kanban_record";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

// ─── Patch KanbanRecord to add toggleSelect ───
patch(KanbanRecord.prototype, {
    async toggleSelect() {
        const resId = this.props.record.resId;
        await this.props.record.model.orm.call(
            "delivery.schedule.line",
            "action_toggle_select",
            [[resId]],
        );
        // Reload the record to reflect the change
        await this.props.record.load();
        this.render(true);
    },
});

// ─── Custom KanbanController with action buttons ───
export class DeliveryKanbanController extends KanbanController {
    setup() {
        super.setup();
        this.actionService = useService("action");
        this.orm = useService("orm");
    }

    /**
     * Get selected (is_selected=True) record IDs from the server
     */
    async _getSelectedIds() {
        return await this.orm.searchRead(
            "delivery.schedule.line",
            [["is_selected", "=", true]],
            ["id"],
        );
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
        const selected = await this._getSelectedIds();
        const ids = selected.map((r) => r.id);
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
        const selected = await this._getSelectedIds();
        const ids = selected.map((r) => r.id);
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
        const selected = await this._getSelectedIds();
        const ids = selected.map((r) => r.id);
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
        window.location.reload();
    }
}

export const deliveryKanbanView = {
    ...kanbanView,
    Controller: DeliveryKanbanController,
    buttonTemplate: "ai_delivery_coordinator.DeliveryKanbanButtons",
};

registry.category("views").add("delivery_kanban", deliveryKanbanView);
