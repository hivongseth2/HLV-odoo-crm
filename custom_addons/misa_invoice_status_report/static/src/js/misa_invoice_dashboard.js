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
const GROUP_PAGE_SIZE = 10;
const SCAN_BATCH_SIZE = 50;

function pad2(n) {
    return String(n).padStart(2, "0");
}

function monthBounds(year, month) {
    const lastDay = new Date(year, month, 0).getDate();
    return {
        from: `${year}-${pad2(month)}-01`,
        to: `${year}-${pad2(month)}-${pad2(lastDay)}`,
    };
}

export class MisaInvoiceDashboard extends Component {
    static template = "misa_invoice_status_report.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        const now = new Date();
        const currentMonth = monthBounds(now.getFullYear(), now.getMonth() + 1);

        this.state = useState({
            isLoading: true,
            isScanning: false,
            isSavingCutoff: false,
            data: null,
            urgent: [],
            // Ngày xuất kho: mặc định tháng hiện tại (quick-pick dropdown ghi vào 2 field này,
            // nhưng người dùng có thể tự sửa tay để lọc 1 ngày cụ thể hoặc 1 khoảng bất kỳ).
            shipFrom: currentMonth.from,
            shipTo: currentMonth.to,
            // Ngày xuất hóa đơn: để trống = không lọc.
            invFrom: "",
            invTo: "",
            cutoffDraft: "",
            activeTab: "urgent", // urgent | warehouse | saler | customer | orders
            salerPage: 1,
            customerPage: 1,
            orders: { rows: [], total: 0, page: 1, pageSize: 20, loading: false },
            showScanPanel: false,
            scanProgress: { done: 0, total: 0 },
            scanLog: [],
            drawerOpen: false,
            drawerPicking: null,
            drawerLines: [],
            drawerLoading: false,
        });

        onWillStart(async () => {
            await this._reloadWithLoading();
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
            options.push({ value: `${year}-${pad2(month)}`, label: `Tháng ${month}/${year}` });
            month -= 1;
            if (month === 0) {
                month = 12;
                year -= 1;
            }
        }
        return options;
    }

    /** Dropdown tháng chỉ "khớp" khi shipFrom/shipTo đúng bằng trọn 1 tháng; ngược lại coi như "Tất cả". */
    get monthDropdownValue() {
        for (const opt of this.monthOptions) {
            const [year, month] = opt.value.split("-").map(Number);
            const bounds = monthBounds(year, month);
            if (this.state.shipFrom === bounds.from && this.state.shipTo === bounds.to) {
                return opt.value;
            }
        }
        return "";
    }

    get filterParams() {
        return {
            date_from: this.state.shipFrom || false,
            date_to: this.state.shipTo || false,
            invoice_date_from: this.state.invFrom || false,
            invoice_date_to: this.state.invTo || false,
        };
    }

    switchTab(tab) {
        this.state.activeTab = tab;
        if (tab === "orders") {
            this.loadOrders(this.state.orders.page || 1);
        }
    }

    async _reloadWithLoading() {
        this.state.isLoading = true;
        try {
            await this._reload();
        } catch (e) {
            this.notification.add("Lỗi tải dữ liệu: " + (e.message || e), { type: "danger" });
        }
        this.state.isLoading = false;
    }

    async _reload() {
        const params = this.filterParams;
        const [data, urgent] = await Promise.all([
            this.orm.call("stock.picking", "get_misa_invoice_dashboard_data", [], { ...params }),
            this.orm.call("stock.picking", "get_misa_invoice_urgent_list", [], { limit: 10, ...params }),
            this.loadOrders(1),
        ]);
        this._applyData(data);
        this.state.urgent = urgent;
    }

    _applyData(data) {
        this.state.data = data;
        this.state.cutoffDraft = data.cutoff_date || "";
        this.state.salerPage = 1;
        this.state.customerPage = 1;
    }

    // ===== Bộ lọc ngày xuất kho / ngày xuất hóa đơn =====
    onMonthPick(ev) {
        const value = ev.target.value;
        if (!value) {
            this.state.shipFrom = "";
            this.state.shipTo = "";
        } else {
            const [year, month] = value.split("-").map(Number);
            const bounds = monthBounds(year, month);
            this.state.shipFrom = bounds.from;
            this.state.shipTo = bounds.to;
        }
        this._reloadWithLoading();
    }

    onShipFromChange(ev) {
        this.state.shipFrom = ev.target.value || "";
        this._reloadWithLoading();
    }

    onShipToChange(ev) {
        this.state.shipTo = ev.target.value || "";
        this._reloadWithLoading();
    }

    onInvFromChange(ev) {
        this.state.invFrom = ev.target.value || "";
        this._reloadWithLoading();
    }

    onInvToChange(ev) {
        this.state.invTo = ev.target.value || "";
        this._reloadWithLoading();
    }

    // ===== Kiểm tra MISA (có tiến trình thấy được) =====
    /** Xử lý tuần tự 1 batch, cập nhật log + progress theo từng phiếu. */
    async _processCandidates(candidates) {
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
    }

    /** Không chọn ngày xuất kho nào (Tất cả) => quét 1 batch như trước (an toàn, không quét cả hệ thống).
     * Có chọn khoảng ngày xuất kho => quét hết TOÀN BỘ khoảng đó, vẫn chia nhỏ từng batch 50. */
    async scanNow() {
        if (this.state.isScanning) {
            return;
        }
        this.state.isScanning = true;
        this.state.showScanPanel = true;
        this.state.scanLog = [];
        this.state.scanProgress = { done: 0, total: 0 };
        try {
            const range = { date_from: this.state.shipFrom || false, date_to: this.state.shipTo || false };
            const hasRange = !!(range.date_from || range.date_to);

            if (!hasRange) {
                const resp = await this.orm.call(
                    "stock.picking", "get_misa_invoice_scan_candidates", [], { limit: SCAN_BATCH_SIZE }
                );
                this.state.scanProgress.total = resp.candidates.length;
                await this._processCandidates(resp.candidates);
            } else {
                let total = null;
                // eslint-disable-next-line no-constant-condition
                while (true) {
                    const resp = await this.orm.call(
                        "stock.picking", "get_misa_invoice_scan_candidates", [],
                        { limit: SCAN_BATCH_SIZE, ...range }
                    );
                    if (total === null) {
                        total = resp.total;
                        this.state.scanProgress.total = total;
                    }
                    if (!resp.candidates.length) {
                        break;
                    }
                    await this._processCandidates(resp.candidates);
                    if (this.state.scanProgress.done >= total) {
                        break;
                    }
                }
            }
            await this._reload();
            if (this.state.scanProgress.done) {
                this.notification.add(`Đã kiểm tra xong ${this.state.scanProgress.done} phiếu.`, { type: "success" });
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
            { state: invoiceState || false, ...this.filterParams }
        );
        this.action.doAction(action);
    }

    async openExceptionTile() {
        const action = await this.orm.call(
            "stock.picking", "get_misa_invoice_report_action", [],
            { state: false, exception: true, ...this.filterParams }
        );
        this.action.doAction(action);
    }

    async openMismatchTile() {
        const action = await this.orm.call(
            "stock.picking", "get_misa_invoice_report_action", [],
            { state: false, mismatch: true, ...this.filterParams }
        );
        this.action.doAction(action);
    }

    async openSalerRow(salerCode) {
        const action = await this.orm.call(
            "stock.picking", "get_misa_invoice_report_action", [],
            { state: false, saler_code: salerCode, ...this.filterParams }
        );
        this.action.doAction(action);
    }

    async openCustomerRow(partnerId) {
        const action = await this.orm.call(
            "stock.picking", "get_misa_invoice_report_action", [],
            { state: false, partner_id: partnerId, ...this.filterParams }
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

    // ===== Tab "Đơn hàng" (phẳng, phân trang server-side) =====
    async loadOrders(page) {
        this.state.orders.loading = true;
        try {
            const resp = await this.orm.call(
                "stock.picking", "get_misa_invoice_picking_list", [],
                {
                    limit: this.state.orders.pageSize,
                    offset: (page - 1) * this.state.orders.pageSize,
                    ...this.filterParams,
                }
            );
            this.state.orders.rows = resp.rows;
            this.state.orders.total = resp.total;
            this.state.orders.page = page;
        } catch (e) {
            this.notification.add("Lỗi tải danh sách đơn hàng: " + (e.message || e), { type: "danger" });
        }
        this.state.orders.loading = false;
    }

    get ordersTotalPages() {
        return Math.max(1, Math.ceil(this.state.orders.total / this.state.orders.pageSize));
    }

    ordersPrevPage() {
        if (this.state.orders.page > 1) {
            this.loadOrders(this.state.orders.page - 1);
        }
    }

    ordersNextPage() {
        if (this.state.orders.page < this.ordersTotalPages) {
            this.loadOrders(this.state.orders.page + 1);
        }
    }

    // ===== Phân trang "Theo nhân viên sale" / "Theo khách hàng" (client-side) =====
    get salerTotalPages() {
        const total = (this.state.data && this.state.data.by_saler.length) || 0;
        return Math.max(1, Math.ceil(total / GROUP_PAGE_SIZE));
    }

    get pagedSalers() {
        if (!this.state.data) {
            return [];
        }
        const start = (this.state.salerPage - 1) * GROUP_PAGE_SIZE;
        return this.state.data.by_saler.slice(start, start + GROUP_PAGE_SIZE);
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

    get customerTotalPages() {
        const total = (this.state.data && this.state.data.by_customer.length) || 0;
        return Math.max(1, Math.ceil(total / GROUP_PAGE_SIZE));
    }

    get pagedCustomers() {
        if (!this.state.data) {
            return [];
        }
        const start = (this.state.customerPage - 1) * GROUP_PAGE_SIZE;
        return this.state.data.by_customer.slice(start, start + GROUP_PAGE_SIZE);
    }

    customerPrevPage() {
        if (this.state.customerPage > 1) {
            this.state.customerPage -= 1;
        }
    }

    customerNextPage() {
        if (this.state.customerPage < this.customerTotalPages) {
            this.state.customerPage += 1;
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
