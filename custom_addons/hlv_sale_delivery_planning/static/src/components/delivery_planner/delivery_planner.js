/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class DeliveryPlannerDashboard extends Component {
    static template = "hlv_sale_delivery_planning.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({
            saleOrders: [],
            isLoading: true,
        });

        onWillStart(async () => {
            await this.fetchData();
        });
    }

    async fetchData() {
        this.state.isLoading = true;
        try {
            const result = await this.orm.call(
                "sale.order",
                "get_delivery_dashboard_data",
                []
            );
            this.state.saleOrders = result;
        } catch (error) {
            console.error("Lỗi khi tải dữ liệu bảng điều phối:", error);
        } finally {
            this.state.isLoading = false;
        }
    }

    openSaleOrder(soId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: soId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openPurchaseOrder(poId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "purchase.order",
            res_id: poId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    getPOStatusBadgeClass(state, receiptStatus) {
        if (state === 'cancel') return 'text-bg-secondary';
        if (receiptStatus === 'full') return 'text-bg-success';
        if (receiptStatus === 'partial') return 'text-bg-warning';
        if (state === 'purchase' || state === 'done') return 'text-bg-info';
        return 'text-bg-light text-dark';
    }

    getSOStatusBadgeClass(deliveryStatus) {
        if (deliveryStatus === 'full') return 'text-bg-success';
        if (deliveryStatus === 'partial') return 'text-bg-warning';
        return 'text-bg-info';
    }

    getDatesComparisonClass(soDate, poDate) {
        if (!soDate || !poDate) return '';
        const so = new Date(soDate);
        const po = new Date(poDate);
        if (po > so) return 'text-danger fw-bold';
        return 'text-success';
    }
}

registry.category("actions").add("hlv_sale_delivery_planning.dashboard", DeliveryPlannerDashboard);
