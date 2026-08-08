/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class MisaInvoiceDashboard extends Component {
    static template = "misa_invoice_status_report.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            isLoading: true,
            isScanning: false,
            data: null,
            urgent: [],
        });

        onWillStart(async () => {
            await this.loadAll();
        });
    }

    async loadAll() {
        this.state.isLoading = true;
        try {
            const [data, urgent] = await Promise.all([
                this.orm.call("stock.picking", "get_misa_invoice_dashboard_data", [], {}),
                this.orm.call("stock.picking", "get_misa_invoice_urgent_list", [], { limit: 10 }),
            ]);
            this.state.data = data;
            this.state.urgent = urgent;
        } catch (e) {
            this.notification.add("Lỗi tải dữ liệu: " + (e.message || e), { type: "danger" });
        }
        this.state.isLoading = false;
    }

    async scanNow() {
        if (this.state.isScanning) {
            return;
        }
        this.state.isScanning = true;
        try {
            this.state.data = await this.orm.call(
                "stock.picking", "action_misa_invoice_dashboard_scan_now", [], {}
            );
            this.state.urgent = await this.orm.call(
                "stock.picking", "get_misa_invoice_urgent_list", [], { limit: 10 }
            );
            this.notification.add("Đã kiểm tra lại với MISA.", { type: "success" });
        } catch (e) {
            this.notification.add("Lỗi kiểm tra MISA: " + (e.message || e), { type: "danger" });
        }
        this.state.isScanning = false;
    }

    async openTile(invoiceState) {
        const action = await this.orm.call(
            "stock.picking", "get_misa_invoice_report_action", [], { state: invoiceState || false, exception: false }
        );
        this.action.doAction(action);
    }

    async openExceptionTile() {
        const action = await this.orm.call(
            "stock.picking", "get_misa_invoice_report_action", [], { state: false, exception: true }
        );
        this.action.doAction(action);
    }

    openPicking(pickingId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            res_id: pickingId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openFullList() {
        this.action.doAction("misa_invoice_status_report.action_misa_invoice_status_report");
    }

    formatCurrency(num) {
        if (!num) {
            return "0 ₫";
        }
        return Number(num).toLocaleString("vi-VN", { maximumFractionDigits: 0 }) + " ₫";
    }

    formatDateTime(str) {
        if (!str) {
            return "Chưa từng chạy";
        }
        // Odoo trả datetime UTC dạng "YYYY-MM-DD HH:MM:SS", ghép "Z" để JS parse đúng UTC
        // rồi hiển thị theo giờ trình duyệt.
        const d = new Date(str.replace(" ", "T") + "Z");
        return d.toLocaleString("vi-VN");
    }
}

registry.category("actions").add("misa_invoice_status_report.Dashboard", MisaInvoiceDashboard);
