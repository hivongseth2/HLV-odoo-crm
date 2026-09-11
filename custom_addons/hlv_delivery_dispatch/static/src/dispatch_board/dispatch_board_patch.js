/** @odoo-module **/
/* Thêm nút "Xếp vào chuyến" vào Bảng điều phối giao hàng.

   Patch từ module này, KHÔNG sửa hlv_sale_delivery_planning: component được export và
   mọi template đều có tên nên mở rộng được bằng patch() + t-inherit.

   Dùng lại API chọn đơn có sẵn của bảng (state.selectedSOIds, selectedCount,
   clearAllSelections) để không có hai cơ chế chọn đơn song song. */

import { patch } from "@web/core/utils/patch";
import { useState, onWillStart } from "@odoo/owl";
import { DeliveryPlannerDashboard } from "@hlv_sale_delivery_planning/components/delivery_planner/delivery_planner";

function todayStr() {
    const now = new Date();
    return now.getFullYear() +
        "-" + String(now.getMonth() + 1).padStart(2, "0") +
        "-" + String(now.getDate()).padStart(2, "0");
}

patch(DeliveryPlannerDashboard.prototype, {
    setup() {
        super.setup();
        this.dispatch = useState({
            canDispatch: false,
            modalOpen: false,
            loadingTrips: false,
            saving: false,
            date: todayStr(),
            trips: [],
            selectedTripId: null,
            error: "",
            result: null,
        });
        onWillStart(() => {
            // Không await: bảng này vốn đã nặng, đừng chặn lần render đầu chỉ để biết
            // có hiện một cái nút hay không.
            this.orm.call("hlv.delivery.trip", "can_current_user_dispatch", [])
                .then((can) => { this.dispatch.canDispatch = !!can; })
                .catch(() => { this.dispatch.canDispatch = false; });
        });
    },

    get dispatchSelectedTrip() {
        const id = this.dispatch.selectedTripId;
        return this.dispatch.trips.find((trip) => trip.id === id) || null;
    },

    async openTripAssignModal() {
        if (!this.selectedCount) {
            return;
        }
        this.dispatch.modalOpen = true;
        this.dispatch.error = "";
        this.dispatch.result = null;
        await this.loadAssignableTrips();
    },

    closeTripAssignModal() {
        this.dispatch.modalOpen = false;
        this.dispatch.result = null;
        this.dispatch.error = "";
    },

    async loadAssignableTrips() {
        this.dispatch.loadingTrips = true;
        this.dispatch.error = "";
        try {
            const warehouseId = this.state.filterWarehouseId;
            const trips = await this.orm.call("hlv.delivery.trip", "get_assignable_trips", [], {
                date: this.dispatch.date,
                warehouse_id: warehouseId && warehouseId !== "all" ? parseInt(warehouseId, 10) : false,
            });
            this.dispatch.trips = trips || [];
            const stillThere = this.dispatch.trips.some(
                (trip) => trip.id === this.dispatch.selectedTripId
            );
            if (!stillThere) {
                this.dispatch.selectedTripId = this.dispatch.trips.length
                    ? this.dispatch.trips[0].id
                    : null;
            }
        } catch (error) {
            this.dispatch.trips = [];
            this.dispatch.error = error.message || "Không tải được danh sách chuyến.";
        } finally {
            this.dispatch.loadingTrips = false;
        }
    },

    onTripAssignDateChange(ev) {
        this.dispatch.date = ev.target.value || todayStr();
        this.loadAssignableTrips();
    },

    onTripAssignTripChange(ev) {
        this.dispatch.selectedTripId = parseInt(ev.target.value, 10) || null;
    },

    async assignSelectedToTrip() {
        const tripId = this.dispatch.selectedTripId;
        if (!tripId) {
            this.dispatch.error = "Chọn một chuyến trước đã.";
            return;
        }
        const orderIds = Array.from(this.state.selectedSOIds);
        if (!orderIds.length) {
            this.dispatch.error = "Chưa chọn đơn nào.";
            return;
        }
        this.dispatch.saving = true;
        this.dispatch.error = "";
        try {
            const result = await this.orm.call(
                "hlv.delivery.trip", "assign_sale_orders", [[tripId], orderIds]
            );
            this.dispatch.result = result;
            if (result.assigned.length) {
                this.clearAllSelections();
                await this.loadAssignableTrips();
            }
        } catch (error) {
            this.dispatch.error = error.message || "Không xếp được vào chuyến.";
        } finally {
            this.dispatch.saving = false;
        }
    },

    /** Mở form Kế hoạch ngày để tạo chuyến khi ngày đang chọn chưa có chuyến nào. */
    openPlanDayAction() {
        this.closeTripAssignModal();
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Kế hoạch ngày",
            res_model: "hlv.delivery.plan.day",
            views: [[false, "list"], [false, "form"]],
            context: { default_date: this.dispatch.date },
        });
    },
});
