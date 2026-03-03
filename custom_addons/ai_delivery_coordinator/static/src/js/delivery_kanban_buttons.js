/** @odoo-module **/
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onPatched } from "@odoo/owl";

// ─── Frontend-only selection state (no backend RPC) ───
const selectedIds = new Set();

// ─── Custom KanbanController ───
export class DeliveryKanbanController extends KanbanController {
    setup() {
        super.setup();
        this.actionService = useService("action");
        this.orm = useService("orm");

        // Bind click handler for checkboxes after render
        onMounted(() => this._bindSelectButtons());
        onPatched(() => this._bindSelectButtons());
    }

    _bindSelectButtons() {
        const el = this.rootRef?.el;
        if (!el) return;
        el.querySelectorAll(".delivery_select_btn").forEach((btn) => {
            if (btn._bound) return; // avoid double-binding
            btn._bound = true;
            btn.addEventListener("click", (ev) => {
                ev.preventDefault();
                ev.stopPropagation();
                // Find the record ID from the kanban card
                const card = btn.closest(".o_kanban_record");
                if (!card) return;
                const dataId = card.dataset.id;
                const id = parseInt(dataId);
                if (!id) return;

                if (selectedIds.has(id)) {
                    selectedIds.delete(id);
                } else {
                    selectedIds.add(id);
                }

                // Toggle visual
                const isSelected = selectedIds.has(id);
                card.classList.toggle("delivery_selected", isSelected);
                const icon = btn.querySelector("i");
                if (icon) {
                    icon.className = isSelected
                        ? "fa fa-check-square text-primary delivery_select_icon"
                        : "fa fa-square-o text-muted delivery_select_icon";
                }
            });
        });
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
        const ids = [...selectedIds];
        const action = await this.orm.call(
            "delivery.schedule.line",
            "action_auto_assign_by_tags",
            [ids.length ? ids : []],
        );
        if (action) {
            selectedIds.clear();
            await this.actionService.doAction(action);
        }
    }

    async onAiAssign() {
        const ids = [...selectedIds];
        const action = await this.orm.call(
            "delivery.schedule.line",
            "action_ai_assign_routes",
            [ids.length ? ids : []],
        );
        if (action) {
            selectedIds.clear();
            await this.actionService.doAction(action);
        }
    }

    async onCreateTrip() {
        const ids = [...selectedIds];
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

    onClearSelection() {
        selectedIds.clear();
        const el = this.rootRef?.el;
        if (!el) return;
        el.querySelectorAll(".delivery_selected").forEach((card) => {
            card.classList.remove("delivery_selected");
        });
        el.querySelectorAll(".delivery_select_icon").forEach((icon) => {
            icon.className = "fa fa-square-o text-muted delivery_select_icon";
        });
    }
}

export const deliveryKanbanView = {
    ...kanbanView,
    Controller: DeliveryKanbanController,
    buttonTemplate: "ai_delivery_coordinator.DeliveryKanbanButtons",
};

registry.category("views").add("delivery_kanban", deliveryKanbanView);
