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
const SALER_PAGE_SIZE = 10;

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
            activeTab: "urgent", // "urgent" | "warehouse" | "saler"
            salerPage: 1,
            showScanPanel: false,
            scanProgress: { done: 0, total: 0 },
            scanLog: [],
            drawerOpen: false,
            drawerPicking: null,
            drawerLines: [],
            drawerLoading: false,
        });

        onWillStart(async () => {
            await this.loadAll();
        });
    }

    /** Danh sách tháng có thể chọn: từ mốc đối soát tới tháng hiện tại, nhãn tiếng Việt dạng số. */
    get monthOptions() {
        const cutoff = this.state.data && this.state.data.cutoff_date;
        if (!cutoff) {
            return [];
        }
        const [cutoffYear, cutoffMonth] = cutoff.split("-").map(Number);
        const now = new Date();
        let year = now.getFullYear();
        let month = now.getMonth() + 1;
        const options = [];
        while (year > cutoffYear || (year === cutoffYear && month >= cutoffMonth)) {
            options.push({ value: `${year}-${String(month).padStart(2, "0")}`, label: `Tháng ${month}/${year}` });
            month -= 1;
            if (month === 0) {
                month = 12;
                year -= 1;
            }
        }
        return options;
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

    switchTab(tab) {
        this.state.activeTab = tab;
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
        this.state.salerPage = 1;
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

    /** Quét từng phiếu một (thay vì 1 lệnh lớn chạy âm thầm) để thấy tiến trình thật. */
    async scanNow() {
        if (this.state.isScanning) {
            return;
        }
        this.state.isScanning = true;
        this.state.showScanPanel = true;
        this.state.scanLog = [];
        this.state.scanProgress = { done: 0, total: 0 };
        try {
            const candidates = await this.orm.call(
                "stock.picking", "get_misa_invoice_scan_candidates", [], { limit: 50 }
            );
            this.state.scanProgress.total = candidates.length;
            for (const candidate of candidates) {
                const entry = { name: candidate.name, statusLabel: "Đang kiểm tra...", loading: true, error: false };
                this.state.scanLog.unshift(entry);
                try {
                    const results = await this.orm.call(
                        "stock.picking", "action_check_misa_invoice_status", [[candidate.id]], {}
                    );
                    const result = results && results[0];
                    if (result && result.error) {
                        entry.statusLabel = "Lỗi: " + result.error;
                        entry.error = true;
                    } else if (result) {
                        entry.statusLabel = result.state_label;
                    } else {
                        entry.statusLabel = "Bỏ qua";
                    }
                } catch (e) {
                    entry.statusLabel = "Lỗi: " + (e.message || e);
                    entry.error = true;
                }
                entry.loading = false;
                this.state.scanProgress.done += 1;
            }
            await this._reload();
            if (candidates.length) {
                this.notification.add(`Đã kiểm tra xong ${candidates.length} phiếu.`, { type: "success" });
            } else {
                this.notification.add("Không có phiếu nào cần kiểm tra.", { type: "info" });
            }
        } catch (e) {
            this.notification.add("Lỗi kiểm tra MISA: " + (e.message || e), { type: "danger" });
        }
        this.state.isScanning = false;
    }

    closeScanPanel() {
        if (!this.state.isScanning) {
            this.state.showScanPanel = false;
        }
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

    /** Mở drawer bên phải: chi tiết 1 phiếu + sản phẩm/giá trị đã xuất, thay vì rời trang. */
    async openDrawer(row) {
        this.state.drawerOpen = true;
        this.state.drawerPicking = row;
        this.state.drawerLines = [];
        this.state.drawerLoading = true;
        try {
            this.state.drawerLines = await this.orm.call(
                "stock.picking", "get_misa_invoice_picking_lines", [row.id], {}
            );
        } catch (e) {
            this.notification.add("Lỗi tải chi tiết phiếu: " + (e.message || e), { type: "danger" });
        }
        this.state.drawerLoading = false;
    }

    closeDrawer() {
        this.state.drawerOpen = false;
        this.state.drawerPicking = null;
        this.state.drawerLines = [];
    }

    /** Chỉ đóng drawer khi bấm đúng vùng nền mờ (overlay), không đóng khi bấm bên trong drawer. */
    onDrawerOverlayClick(ev) {
        if (ev.target === ev.currentTarget) {
            this.closeDrawer();
        }
    }

    get drawerLinesTotal() {
        return this.state.drawerLines.reduce((sum, line) => sum + (line.value || 0), 0);
    }

    // ===== Phân trang bảng "Theo nhân viên sale" (client-side, dữ liệu đã tải sẵn) =====
    get salerTotalPages() {
        const total = (this.state.data && this.state.data.by_saler.length) || 0;
        return Math.max(1, Math.ceil(total / SALER_PAGE_SIZE));
    }

    get pagedSalers() {
        if (!this.state.data) {
            return [];
        }
        const start = (this.state.salerPage - 1) * SALER_PAGE_SIZE;
        return this.state.data.by_saler.slice(start, start + SALER_PAGE_SIZE);
    }

    salerPrevPage() {
        if (this.state.salerPage > 1) {
            this.state.salerPage -= 1;
        }
    }

    salerNextPage() {
        if (this.state.salerPage < this.salerTotalPages) {
            this.state.salerPage += 1;
        }
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
