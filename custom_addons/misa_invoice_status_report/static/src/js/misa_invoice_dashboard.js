/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

// Cùng bộ status palette đã validate (xem dataviz skill): good/warning/serious/critical
// + màu trung tính cho "chưa kiểm tra" và "ngoại lệ".
const DONUT_COLORS = {
    invoiced: "#0ca30c",
    requested: "#fab219",
    missing: "#d03b3b",
    exception: "#4a3aa7",
    not_checked: "#c3c2b7",
};
const DONUT_RADIUS = 54;
const DONUT_CIRCUMFERENCE = 2 * Math.PI * DONUT_RADIUS;

export class MisaInvoiceDashboard extends Component {
    static template = "misa_invoice_status_report.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            isLoading: true,
            isScanning: false,
            isSavingCutoff: false,
            data: null,
            urgent: [],
            cutoffDraft: "",
            monthFilter: "", // "" = tất cả (kể từ mốc đối soát); "YYYY-MM" = lọc theo tháng
        });

        onWillStart(async () => {
            await this.loadAll();
        });
    }

    /** Chuyển "YYYY-MM" thành {date_from, date_to} (đầu/cuối tháng). "" => không lọc. */
    get monthRange() {
        if (!this.state.monthFilter) {
            return { date_from: false, date_to: false };
        }
        const [year, month] = this.state.monthFilter.split("-").map(Number);
        const lastDay = new Date(year, month, 0).getDate();
        const pad = (n) => String(n).padStart(2, "0");
        return {
            date_from: `${year}-${pad(month)}-01`,
            date_to: `${year}-${pad(month)}-${pad(lastDay)}`,
        };
    }

    async loadAll() {
        this.state.isLoading = true;
        try {
            await this._reload();
        } catch (e) {
            this.notification.add("Lỗi tải dữ liệu: " + (e.message || e), { type: "danger" });
        }
        this.state.isLoading = false;
    }

    async _reload() {
        const range = this.monthRange;
        const [data, urgent] = await Promise.all([
            this.orm.call("stock.picking", "get_misa_invoice_dashboard_data", [], { ...range }),
            this.orm.call("stock.picking", "get_misa_invoice_urgent_list", [], { limit: 10, ...range }),
        ]);
        this._applyData(data);
        this.state.urgent = urgent;
    }

    _applyData(data) {
        this.state.data = data;
        this.state.cutoffDraft = data.cutoff_date || "";
    }

    async onMonthChange(ev) {
        this.state.monthFilter = ev.target.value || "";
        this.state.isLoading = true;
        try {
            await this._reload();
        } catch (e) {
            this.notification.add("Lỗi lọc theo tháng: " + (e.message || e), { type: "danger" });
        }
        this.state.isLoading = false;
    }

    async clearMonthFilter() {
        if (!this.state.monthFilter) {
            return;
        }
        this.state.monthFilter = "";
        this.state.isLoading = true;
        try {
            await this._reload();
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
            await this.orm.call("stock.picking", "action_misa_invoice_dashboard_scan_now", [], {});
            await this._reload();
            this.notification.add("Đã kiểm tra lại với MISA.", { type: "success" });
        } catch (e) {
            this.notification.add("Lỗi kiểm tra MISA: " + (e.message || e), { type: "danger" });
        }
        this.state.isScanning = false;
    }

    onCutoffChange(ev) {
        this.state.cutoffDraft = ev.target.value;
    }

    async saveCutoff() {
        if (!this.state.cutoffDraft || this.state.isSavingCutoff) {
            return;
        }
        this.state.isSavingCutoff = true;
        try {
            await this.orm.call(
                "stock.picking", "set_misa_invoice_cutoff_date", [], { date_str: this.state.cutoffDraft }
            );
            await this._reload();
            this.notification.add("Đã cập nhật mốc đối soát.", { type: "success" });
        } catch (e) {
            this.notification.add("Lỗi lưu cấu hình: " + (e.message || e), { type: "danger" });
        }
        this.state.isSavingCutoff = false;
    }

    /** invoiceState falsy (false/undefined) => không lọc trạng thái, dùng cho "Xem tất cả". */
    async openTile(invoiceState) {
        const action = await this.orm.call(
            "stock.picking", "get_misa_invoice_report_action", [],
            { state: invoiceState || false, ...this.monthRange }
        );
        this.action.doAction(action);
    }

    async openExceptionTile() {
        const action = await this.orm.call(
            "stock.picking", "get_misa_invoice_report_action", [],
            { state: false, exception: true, ...this.monthRange }
        );
        this.action.doAction(action);
    }

    async openMismatchTile() {
        const action = await this.orm.call(
            "stock.picking", "get_misa_invoice_report_action", [],
            { state: false, mismatch: true, ...this.monthRange }
        );
        this.action.doAction(action);
    }

    async openSalerRow(salerCode) {
        const action = await this.orm.call(
            "stock.picking", "get_misa_invoice_report_action", [],
            { state: false, saler_code: salerCode, ...this.monthRange }
        );
        this.action.doAction(action);
    }

    openFullList() {
        return this.openTile(false);
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

    get donutSegments() {
        const data = this.state.data;
        if (!data || !data.total) {
            return [];
        }
        const parts = [
            { key: "invoiced", value: data.counts.invoiced },
            { key: "requested", value: data.counts.requested },
            { key: "missing", value: data.counts.missing },
            { key: "exception", value: data.exception_count },
            { key: "not_checked", value: data.counts.not_checked },
        ];
        let cumulative = 0;
        const segments = [];
        for (const part of parts) {
            if (!part.value) {
                continue;
            }
            const length = (part.value / data.total) * DONUT_CIRCUMFERENCE;
            segments.push({
                key: part.key,
                color: DONUT_COLORS[part.key],
                dasharray: `${length} ${DONUT_CIRCUMFERENCE - length}`,
                dashoffset: -cumulative,
            });
            cumulative += length;
        }
        return segments;
    }

    get invoicedPercent() {
        const data = this.state.data;
        if (!data || !data.total) {
            return 0;
        }
        return Math.round((data.counts.invoiced / data.total) * 100);
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
