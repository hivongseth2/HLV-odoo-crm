/** @odoo-module */

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class StockDashboardField extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        const today = new Date();
        const dateStr = today.getFullYear() + "-" + String(today.getMonth() + 1).padStart(2, '0') + "-" + String(today.getDate()).padStart(2, '0');

        this.state = useState({
            date: dateStr, // Default today YYYY-MM-DD Local
            data: { total: 0, full: 0, partial: 0, not_full: 0 },
            warehouse_name: this.props.record.data.name || "Unknown",
        });

        onWillStart(async () => {
            try {
                if (this.props.record.data[this.props.name]) {
                    const rawData = JSON.parse(this.props.record.data[this.props.name]);
                    if (rawData.misa) {
                        this.state.data = rawData.misa;
                    }
                }
            } catch (e) {
                console.error("Error parsing initial dashboard data", e);
            }
        });

        onWillUpdateProps((nextProps) => {
            // Handle updates if needed
        });
    }

    async onDateChanged(ev) {
        if (ev && ev.stopPropagation) {
            ev.stopPropagation();
        }
        const newDate = ev.target.value;
        this.state.date = newDate;
        await this.fetchData(newDate);
    }

    ignoreClick(ev) {
        if (ev) {
            ev.stopPropagation();
        }
    }

    onWarehouseClick(ev) {
        if (ev) {
            ev.stopPropagation();
            ev.preventDefault();
        }
        this.onOrderClick('all');
    }

    onViewAllClick(ev) {
        if (ev) {
            ev.stopPropagation();
        }
        const warehouseId = this.props.record.resId;
        this.action.doAction({
            name: `Đơn MISA (Tất cả)`,
            type: 'ir.actions.act_window',
            res_model: 'sale.order',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: [
                ['warehouse_id', '=', warehouseId],
                ['state', 'in', ['sale', 'done']]
            ],
            context: { create: false },
        });
    }

    async fetchData(date) {
        try {
            const warehouseId = this.props.record.resId;
            const result = await this.orm.call("stock.warehouse", "get_dashboard_data", [warehouseId, date]);
            this.state.data = result;
        } catch (e) {
            console.error("Error fetching dashboard data", e);
        }
    }

    onOrderClick(filterType) {
        const warehouseId = this.props.record.resId;
        const date = this.state.date;

        let domain = [
            ['warehouse_id', '=', warehouseId],
            ['x_studio_misa_order_date', '=', date],
            ['state', 'in', ['sale', 'done']]
        ];

        let name = `Đơn MISA ${this.displayDate}`;

        if (filterType === 'full') {
            domain.push(['delivery_status', '=', 'full']);
            name += " (Đã xong)";
        } else if (filterType === 'partial') {
            domain.push(['delivery_status', '=', 'partial']);
            name += " (1 Phần)";
        } else if (filterType === 'not_full') {
            domain.push(['delivery_status', '!=', 'full']);
            name += " (Chưa giao / Chưa xong)";
        }

        this.action.doAction({
            name: name,
            type: 'ir.actions.act_window',
            res_model: 'sale.order',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
            context: { create: false },
        });
    }

    get displayDate() {
        const today = new Date();
        const dateStr = today.getFullYear() + "-" + String(today.getMonth() + 1).padStart(2, '0') + "-" + String(today.getDate()).padStart(2, '0');
        if (this.state.date === dateStr) {
            return "Hôm nay";
        }

        try {
            const parts = this.state.date.split('-');
            return `${parts[2]}/${parts[1]}/${parts[0]}`;
        } catch (e) {
            return this.state.date;
        }
    }
}

StockDashboardField.template = "stock_warehouse_dashboard.StockDashboardField";
StockDashboardField.props = {
    ...standardFieldProps,
};

export const stockDashboardField = {
    component: StockDashboardField,
    supportedTypes: ["text"],
};

registry.category("fields").add("stock_dashboard_field", stockDashboardField);
