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
            activeTab: "urgent", // urgent | warehouse | saler | customer | daily | pickings | orders
            salerPage: 1,
            customerPage: 1,
            statusSummary: null,
            // Tab "Theo ngày": có thể lọc theo 1 nhân viên sale + gộp theo tuần.
            dailyTab: { rows: [], loading: false, weekly: false, salerCode: "" },
            // Tab "Phiếu xuất kho": phẳng, key là stock.picking (KBC/OUT/...).
            pickingsTab: { rows: [], total: 0, page: 1, pageSize: 20, loading: false },
            // Tab "Đơn hàng": phẳng, key là sale.order (DH...) — 1 đơn có thể gộp nhiều phiếu.
            ordersTab: { rows: [], total: 0, page: 1, pageSize: 20, loading: false, search: "", searchDraft: "" },
            showScanPanel: false,
            scanProgress: { done: 0, total: 0 },
            scanLog: [],
            drawerOpen: false,
            drawerPicking: null,
            drawerLines: [],
            drawerLoading: false,
            groupDrawerOpen: false,
            groupDrawerType: null, // "saler" | "customer"
            groupDrawerRow: null,
            orderDrawerOpen: false,
            orderDrawerRow: null,
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
        if (tab === "pickings") {
            this.loadPickingsTab(this.state.pickingsTab.page || 1);
        } else if (tab === "orders") {
            this.loadOrdersTab(this.state.ordersTab.page || 1);
        } else if (tab === "daily") {
            this.loadDailyTab();
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
        const [data, urgent, statusSummary] = await Promise.all([
            this.orm.call("stock.picking", "get_misa_invoice_dashboard_data", [], { ...params }),
            this.orm.call("stock.picking", "get_misa_invoice_urgent_list", [], { limit: 10, ...params }),
            this.orm.call("stock.picking", "get_misa_invoice_status_summary", [], { ...params }),
            this.loadPickingsTab(1),
            this.loadOrdersTab(1),
            this.loadDailyTab(),
        ]);
        this._applyData(data);
        this.state.urgent = urgent;
        this.state.statusSummary = statusSummary;
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
    /** Kiểm tra 1 batch bằng 1 lệnh gọi duy nhất (map đề nghị xuất HĐ dùng chung, xử lý đúng
     * trường hợp 1 đề nghị đại diện cho nhiều phiếu) — sau đó "rải" log ra cho người dùng
     * thấy tiến trình chạy dần (độ trễ nhỏ ở đây chỉ để hiển thị, không phải do gọi API). */
    async _processCandidates(candidates) {
        let results = [];
        try {
            results = await this.orm.call(
                "stock.picking", "action_check_misa_invoice_status_batch", [candidates.map((c) => c.id)], {}
            );
        } catch (e) {
            for (const candidate of candidates) {
                this.state.scanLog.unshift({
                    name: candidate.name, statusLabel: "Lỗi: " + (e.message || e), loading: false, error: true,
                });
                this.state.scanProgress.done += 1;
            }
            return;
        }
        const byId = new Map(results.map((r) => [r.id, r]));
        for (const candidate of candidates) {
            const result = byId.get(candidate.id);
            const entry = { name: candidate.name, loading: false, error: false, statusLabel: "Bỏ qua" };
            if (result && result.error) {
                entry.statusLabel = "Lỗi: " + result.error;
                entry.error = true;
            } else if (result) {
                entry.statusLabel = result.state_label;
            }
            this.state.scanLog.unshift(entry);
            this.state.scanProgress.done += 1;
            // eslint-disable-next-line no-await-in-loop
            await new Promise((resolve) => setTimeout(resolve, 60));
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

    /** Bấm vào dòng nhân viên sale/khách hàng: mở drawer tổng quan trước (dữ liệu đã có
     * sẵn trong `row`, không cần gọi thêm) — nút "Xem danh sách phiếu" trong drawer mới
     * điều hướng sang danh sách lọc như hành vi cũ. */
    openGroupDrawer(type, row) {
        this.state.groupDrawerType = type;
        this.state.groupDrawerRow = row;
        this.state.groupDrawerOpen = true;
    }

    closeGroupDrawer() {
        this.state.groupDrawerOpen = false;
        this.state.groupDrawerType = null;
        this.state.groupDrawerRow = null;
    }

    onGroupDrawerOverlayClick(ev) {
        if (ev.target === ev.currentTarget) {
            this.closeGroupDrawer();
        }
    }

    viewGroupDrawerList() {
        const row = this.state.groupDrawerRow;
        if (this.state.groupDrawerType === "saler") {
            return this.openSalerRow(row.saler_code);
        }
        return this.openCustomerRow(row.partner_id);
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

    // ===== Tab "Theo ngày" (tổng tiền xuất kho vs đã xuất HĐ theo ngày/tuần) =====
    async loadDailyTab() {
        this.state.dailyTab.loading = true;
        try {
            this.state.dailyTab.rows = await this.orm.call(
                "stock.picking", "get_misa_invoice_daily_stats", [],
                {
                    ...this.filterParams,
                    saler_code: this.state.dailyTab.salerCode || false,
                    weekly: this.state.dailyTab.weekly,
                }
            );
        } catch (e) {
            this.notification.add("Lỗi tải thống kê theo ngày: " + (e.message || e), { type: "danger" });
        }
        this.state.dailyTab.loading = false;
    }

    onDailyWeeklyToggle(ev) {
        this.state.dailyTab.weekly = ev.target.checked;
        this.loadDailyTab();
    }

    onDailySalerChange(ev) {
        this.state.dailyTab.salerCode = ev.target.value || "";
        this.loadDailyTab();
    }

    // ===== Tab "Phiếu xuất kho" (phẳng, key = stock.picking, phân trang server-side) =====
    async loadPickingsTab(page) {
        this.state.pickingsTab.loading = true;
        try {
            const resp = await this.orm.call(
                "stock.picking", "get_misa_invoice_picking_list", [],
                {
                    limit: this.state.pickingsTab.pageSize,
                    offset: (page - 1) * this.state.pickingsTab.pageSize,
                    ...this.filterParams,
                }
            );
            this.state.pickingsTab.rows = resp.rows;
            this.state.pickingsTab.total = resp.total;
            this.state.pickingsTab.page = page;
        } catch (e) {
            this.notification.add("Lỗi tải danh sách phiếu xuất kho: " + (e.message || e), { type: "danger" });
        }
        this.state.pickingsTab.loading = false;
    }

    get pickingsTabTotalPages() {
        return Math.max(1, Math.ceil(this.state.pickingsTab.total / this.state.pickingsTab.pageSize));
    }

    pickingsTabPrevPage() {
        if (this.state.pickingsTab.page > 1) {
            this.loadPickingsTab(this.state.pickingsTab.page - 1);
        }
    }

    pickingsTabNextPage() {
        if (this.state.pickingsTab.page < this.pickingsTabTotalPages) {
            this.loadPickingsTab(this.state.pickingsTab.page + 1);
        }
    }

    // ===== Tab "Đơn hàng" (phẳng, key = sale.order DH..., phân trang server-side, có search) =====
    async loadOrdersTab(page) {
        this.state.ordersTab.loading = true;
        try {
            const resp = await this.orm.call(
                "stock.picking", "get_misa_invoice_order_list", [],
                {
                    limit: this.state.ordersTab.pageSize,
                    offset: (page - 1) * this.state.ordersTab.pageSize,
                    search: this.state.ordersTab.search || false,
                    ...this.filterParams,
                }
            );
            this.state.ordersTab.rows = resp.rows;
            this.state.ordersTab.total = resp.total;
            this.state.ordersTab.page = page;
        } catch (e) {
            this.notification.add("Lỗi tải danh sách đơn hàng: " + (e.message || e), { type: "danger" });
        }
        this.state.ordersTab.loading = false;
    }

    get ordersTabTotalPages() {
        return Math.max(1, Math.ceil(this.state.ordersTab.total / this.state.ordersTab.pageSize));
    }

    ordersTabPrevPage() {
        if (this.state.ordersTab.page > 1) {
            this.loadOrdersTab(this.state.ordersTab.page - 1);
        }
    }

    ordersTabNextPage() {
        if (this.state.ordersTab.page < this.ordersTabTotalPages) {
            this.loadOrdersTab(this.state.ordersTab.page + 1);
        }
    }

    onOrdersSearchInput(ev) {
        this.state.ordersTab.searchDraft = ev.target.value;
    }

    onOrdersSearchKeydown(ev) {
        if (ev.key === "Enter") {
            this.submitOrdersSearch();
        }
    }

    submitOrdersSearch() {
        this.state.ordersTab.search = this.state.ordersTab.searchDraft.trim();
        this.loadOrdersTab(1);
    }

    clearOrdersSearch() {
        this.state.ordersTab.search = "";
        this.state.ordersTab.searchDraft = "";
        this.loadOrdersTab(1);
    }

    /** Bấm vào dòng đơn hàng: mở drawer chi tiết (dữ liệu đã có sẵn `pickings` con từ
     * backend) — nút trong drawer mở thẳng form đơn bán trên Odoo. */
    openOrderDrawer(row) {
        this.state.orderDrawerRow = row;
        this.state.orderDrawerOpen = true;
    }

    closeOrderDrawer() {
        this.state.orderDrawerOpen = false;
        this.state.orderDrawerRow = null;
    }

    onOrderDrawerOverlayClick(ev) {
        if (ev.target === ev.currentTarget) {
            this.closeOrderDrawer();
        }
    }

    openOrderForm() {
        const row = this.state.orderDrawerRow;
        if (!row) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: row.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    medalIcon(rank) {
        return { 1: "🥇", 2: "🥈", 3: "🥉" }[rank] || "";
    }

    completionClass(pct) {
        if (pct >= 90) {
            return "miv-cell-good";
        }
        if (pct >= 70) {
            return "miv-cell-warning";
        }
        return "miv-cell-critical";
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
