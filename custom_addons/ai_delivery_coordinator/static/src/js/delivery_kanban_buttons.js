/** @odoo-module **/
import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onWillUnmount } from "@odoo/owl";

// ─── Frontend-only selection (zero RPC) ───
const selectedIds = new Set();

/**
 * Bulletproof click handler.
 * Uses capture phase + stopImmediatePropagation to prevent
 * oe_kanban_global_click from opening the form.
 */
function handleSelectClick(ev) {
    // Find the select button (could click on <a> or <i>)
    const btn = ev.target.closest(".delivery_select_btn");
    if (!btn) return;

    // CRITICAL: Stop everything - prevent form opening
    ev.stopImmediatePropagation();
    ev.stopPropagation();
    ev.preventDefault();

    const card = btn.closest(".o_kanban_record");
    if (!card) return;

    const id = parseInt(card.dataset.id);
    if (!id) return;

    // Toggle
    if (selectedIds.has(id)) {
        selectedIds.delete(id);
    } else {
        selectedIds.add(id);
    }

    // Instant visual
    const isSelected = selectedIds.has(id);
    card.classList.toggle("delivery_selected", isSelected);
    const icon = btn.querySelector(".delivery_select_icon");
    if (icon) {
        icon.className = isSelected
            ? "fa fa-check-square-o text-primary delivery_select_icon"
            : "fa fa-square-o text-muted delivery_select_icon";
    }
}

// ─── Custom Controller ───
export class DeliveryKanbanController extends KanbanController {
    setup() {
        super.setup();
        this.actionService = useService("action");
        this.orm = useService("orm");

        onMounted(() => {
            // Capture phase = fires BEFORE any other handler
            document.addEventListener("click", handleSelectClick, true);
        });
        onWillUnmount(() => {
            document.removeEventListener("click", handleSelectClick, true);
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
        document.querySelectorAll(".delivery_selected").forEach((c) => {
            c.classList.remove("delivery_selected");
        });
        document.querySelectorAll(".delivery_select_icon").forEach((i) => {
            i.className = "fa fa-square-o text-muted delivery_select_icon";
        });
    }
}

export const deliveryKanbanView = {
    ...kanbanView,
    Controller: DeliveryKanbanController,
    buttonTemplate: "ai_delivery_coordinator.DeliveryKanbanButtons",
};

registry.category("views").add("delivery_kanban", deliveryKanbanView);
