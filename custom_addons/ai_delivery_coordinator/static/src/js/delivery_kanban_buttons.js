/** @odoo-module **/
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onWillUnmount } from "@odoo/owl";

// ─── Frontend-only selection (zero RPC) ───
const selectedIds = new Set();

/**
 * Global click handler using event delegation on document.
 * This works regardless of when kanban records render.
 */
function onGlobalClick(ev) {
    const btn = ev.target.closest(".delivery_select_btn");
    if (!btn) return;

    ev.preventDefault();
    ev.stopPropagation();

    const card = btn.closest(".o_kanban_record");
    if (!card) return;

    // Get record ID from the card's data-id attribute
    const id = parseInt(card.dataset.id);
    if (!id) return;

    // Toggle selection
    if (selectedIds.has(id)) {
        selectedIds.delete(id);
    } else {
        selectedIds.add(id);
    }

    // Instant visual feedback
    const isSelected = selectedIds.has(id);
    card.classList.toggle("delivery_selected", isSelected);
    const icon = btn.querySelector(".delivery_select_icon");
    if (icon) {
        icon.className = isSelected
            ? "fa fa-check-square text-primary delivery_select_icon"
            : "fa fa-square-o text-muted delivery_select_icon";
    }
}

// ─── Custom KanbanController ───
export class DeliveryKanbanController extends KanbanController {
    setup() {
        super.setup();
        this.actionService = useService("action");
        this.orm = useService("orm");

        onMounted(() => {
            document.addEventListener("click", onGlobalClick, true);
        });
        onWillUnmount(() => {
            document.removeEventListener("click", onGlobalClick, true);
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
        document.querySelectorAll(".delivery_selected").forEach((card) => {
            card.classList.remove("delivery_selected");
        });
        document.querySelectorAll(".delivery_select_icon").forEach((icon) => {
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
