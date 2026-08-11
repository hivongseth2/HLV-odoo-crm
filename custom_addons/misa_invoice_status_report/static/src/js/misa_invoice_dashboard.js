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
const STATE_LABELS = {
    not_checked: "Chưa kiểm tra",
    missing: "Chưa có đề nghị xuất HĐ",
    requested: "Đã đề nghị, chờ HĐ",
    invoiced: "Đã xuất hóa đơn",
    exception: "Ngoại lệ",
};
// Dùng cho dropdown lọc trạng thái ở tab "Phiếu xuất kho"/"Đơn hàng" — không có "exception"
// vì đó là 1 cờ boolean riêng (misa_invoice_exception), không phải giá trị misa_invoice_state.
const PICKING_STATE_FILTER_OPTIONS = [
    { value: "not_checked", label: "Chưa kiểm tra" },
    { value: "missing", label: "Chưa có đề nghị xuất HĐ" },
    { value: "requested", label: "Đã đề nghị, chờ HĐ" },
    { value: "invoiced", label: "Đã xuất hóa đơn" },
];
// Trạng thái riêng của hóa đơn điện tử Shopee (meInvoice) — khác hẳn tập trạng thái MISA ở
// trên vì đây là model meinvoice.invoice.state, không phải misa_invoice_state.
const SHOPEE_STATE_FILTER_OPTIONS = [
    { value: "missing", label: "Chưa có HĐĐT" },
    { value: "draft", label: "Nháp, chưa phát hành" },
    { value: "submitted", label: "Đã gửi, chờ CQT duyệt" },
    { value: "rejected", label: "Bị từ chối" },
    { value: "accepted", label: "Đã phát hành" },
];
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
            pickingsTab: {
                rows: [], total: 0, page: 1, pageSize: 20, loading: false, search: "", searchDraft: "",
                stateFilter: "", salerFilter: "",
            },
            // Tab "Đơn hàng": phẳng, key là sale.order (DH...) — 1 đơn có thể gộp nhiều phiếu.
            ordersTab: {
                rows: [], total: 0, page: 1, pageSize: 20, loading: false, search: "", searchDraft: "",
                stateFilter: "", salerFilter: "", multiRequestOnly: false,
            },
            // Tab "Đơn Shopee": hóa đơn điện tử meInvoice riêng (amis_callback), chỉ xem —
            // phân trang/lọc phía server nhưng trạng thái tính từ model khác nên load nguyên
            // trang rồi cắt theo offset/limit ở backend (xem get_misa_invoice_shopee_list).
            shopeeTab: {
                rows: [], total: 0, page: 1, pageSize: 20, loading: false, search: "", searchDraft: "",
                stateFilter: "",
            },
            // Tab "Đơn hải quan": hóa đơn MISA xuất TRƯỚC khi có phiếu xuất kho Odoo — nhập
            // tay số hóa đơn, xem preview trước khi ghi nhận (fetching/saving riêng biệt).
            customsTab: {
                rows: [], total: 0, page: 1, pageSize: 20, loading: false, search: "", searchDraft: "",
                invInput: "", fetching: false, saving: false, preview: null,
            },
            showScanPanel: false,
            scanProgress: { done: 0, total: 0 },
            scanLog: [],
            // Chỉ dùng để backfill 1 lần (VD sau khi sửa logic ghép nhiều phiếu/1 đề nghị) —
            // quét lại CẢ phiếu đã "Đã xuất HĐ", vốn bị loại khỏi vòng quét thường ngày.
            includeInvoiced: false,
            drawerOpen: false,
            drawerPicking: null,
            drawerLines: [],
            drawerSiblings: [],
            drawerLoading: false,
            // Đối chiếu từng dòng hàng với MISA — tải riêng theo yêu cầu (bấm nút), không tự
            // động gọi khi mở drawer vì tốn thêm 1 lệnh gọi MISA mỗi lần.
            reconciliation: null,
            reconciliationLoading: false,
            reconciliationOpen: false,
            groupDrawerOpen: false,
            groupDrawerType: null, // "saler" | "customer"
            groupDrawerRow: null,
            orderDrawerOpen: false,
            orderDrawerRow: null,
            orderCheckLoading: false,
        });

        onWillStart(async () => {
            await this._reloadWithLoading();
        });
    }

    get pickingStateFilterOptions() {
        return PICKING_STATE_FILTER_OPTIONS;
    }

    get shopeeStateFilterOptions() {
        return SHOPEE_STATE_FILTER_OPTIONS;
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

    /** Đối chiếu tổng tiền xuất kho (MISA + Shopee) — tính thẳng từ state.statusSummary đã
     * tải sẵn (không gọi thêm API): dòng 'invoiced' chỉ cộng invoice_amount cho đúng
     * misa_invoice_state == 'invoiced' (xem get_misa_invoice_status_summary), dòng 'shopee'
     * đã CỘNG SẴN vào 'total' ở backend nên còn lại = total - misa - shopee luôn khớp. */
    get reconciliationTotals() {
        const summary = this.state.statusSummary;
        if (!summary) {
            return null;
        }
        const totalActual = summary.total.actual_amount;
        const misaInvoiced = summary.invoiced.invoice_amount;
        const shopeeInvoiced = summary.shopee ? summary.shopee.invoice_amount : 0;
        return {
            total_actual_amount: totalActual,
            misa_invoiced_amount: misaInvoiced,
            shopee_invoiced_amount: shopeeInvoiced,
            outstanding_amount: totalActual - misaInvoiced - shopeeInvoiced,
        };
    }

    /** Bấm vào 1 ô đối chiếu tổng — nhảy tới đúng tab/filter thể hiện nhóm đó. */
    openReconciliationGroup(kind) {
        if (kind === "misa") {
            this.state.pickingsTab.stateFilter = "invoiced";
            this.switchTab("pickings");
        } else if (kind === "shopee") {
            this.state.shopeeTab.stateFilter = "accepted";
            this.switchTab("shopee");
        } else {
            // 'total' và 'outstanding' không map được về đúng 1 giá trị filter duy nhất
            // (còn lại = gồm nhiều trạng thái) — bỏ filter, để xem hết rồi tự đọc theo cột.
            this.state.pickingsTab.stateFilter = "";
            this.switchTab("pickings");
        }
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
        } else if (tab === "shopee") {
            this.loadShopeeTab(this.state.shopeeTab.page || 1);
        } else if (tab === "customs") {
            this.loadCustomsTab(this.state.customsTab.page || 1);
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
            this.loadShopeeTab(1),
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
            const includeInvoiced = this.state.includeInvoiced;

            if (!hasRange) {
                const resp = await this.orm.call(
                    "stock.picking", "get_misa_invoice_scan_candidates", [],
                    { limit: SCAN_BATCH_SIZE, include_invoiced: includeInvoiced }
                );
                this.state.scanProgress.total = resp.candidates.length;
                await this._processCandidates(resp.candidates);
            } else {
                let total = null;
                // eslint-disable-next-line no-constant-condition
                while (true) {
                    const resp = await this.orm.call(
                        "stock.picking", "get_misa_invoice_scan_candidates", [],
                        { limit: SCAN_BATCH_SIZE, include_invoiced: includeInvoiced, ...range }
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

    onIncludeInvoicedToggle(ev) {
        this.state.includeInvoiced = ev.target.checked;
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

    async openWarehouseRow(warehouseId) {
        const action = await this.orm.call(
            "stock.picking", "get_misa_invoice_report_action", [],
            { state: false, warehouse_id: warehouseId, ...this.filterParams }
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
        const type = this.state.groupDrawerType;
        if (type === "saler") {
            return this.openSalerRow(row.saler_code);
        }
        if (type === "customer") {
            return this.openCustomerRow(row.partner_id);
        }
        if (type === "warehouse") {
            return this.openWarehouseRow(row.warehouse_id);
        }
        if (type === "state") {
            this.closeGroupDrawer();
            if (row.key === "exception") {
                return this.openExceptionTile();
            }
            return this.openTile(row.key);
        }
        if (type === "day") {
            // Chuyển sang tab "Phiếu xuất kho", lọc đúng ngày/tuần đang xem trong drawer.
            this.closeGroupDrawer();
            this.state.shipFrom = row.date_from;
            this.state.shipTo = row.date_to;
            this.state.activeTab = "pickings";
            return this._reloadWithLoading();
        }
        return undefined;
    }

    /** Bấm vào donut/legend/tile trạng thái: mở drawer thống kê nhanh cho đúng trạng thái đó
     * (dữ liệu đã có sẵn trong state.statusSummary, không cần gọi thêm). */
    openStateDrawer(stateKey) {
        const summary = this.state.statusSummary && this.state.statusSummary[stateKey];
        if (!summary) {
            return;
        }
        this.openGroupDrawer("state", { key: stateKey, label: STATE_LABELS[stateKey] || stateKey, ...summary });
    }

    /** "Xem tất cả" — tab-aware: đang ở tab "Đơn hàng" thì mở danh sách lấy ĐƠN HÀNG làm
     * key (sale.order), các tab còn lại (kể cả "Phiếu xuất kho") mở danh sách lấy PHIẾU
     * XUẤT KHO làm key (stock.picking) như trước giờ. */
    openFullList() {
        if (this.state.activeTab === "orders") {
            return this.action.doAction("misa_invoice_status_report.action_misa_invoice_order_list_page");
        }
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
        this.state.drawerSiblings = [];
        this.state.drawerLoading = true;
        this.state.reconciliation = null;
        this.state.reconciliationOpen = false;
        try {
            const [lines, siblings] = await Promise.all([
                this.orm.call("stock.picking", "get_misa_invoice_picking_lines", [row.id], {}),
                this.orm.call("stock.picking", "get_misa_invoice_picking_siblings", [row.id], {}),
            ]);
            this.state.drawerLines = lines;
            this.state.drawerSiblings = siblings;
        } catch (e) {
            this.notification.add("Lỗi tải chi tiết phiếu: " + (e.message || e), { type: "danger" });
        }
        this.state.drawerLoading = false;
    }

    /** Bấm nút "Đối chiếu từng dòng với MISA" — tải riêng (không tự động khi mở drawer) vì
     * tốn thêm 1 lệnh gọi MISA; tự gộp cả nhóm phiếu nếu phiếu này nằm trong 1 đề nghị gộp
     * chung nhiều phiếu (xử lý ở backend). */
    async loadReconciliation() {
        if (this.state.reconciliationOpen) {
            this.state.reconciliationOpen = false;
            return;
        }
        this.state.reconciliationOpen = true;
        if (this.state.reconciliation) {
            return;
        }
        const pickingId = this.state.drawerPicking && this.state.drawerPicking.id;
        if (!pickingId) {
            return;
        }
        this.state.reconciliationLoading = true;
        try {
            const result = await this.orm.call(
                "stock.picking", "get_misa_invoice_line_reconciliation", [pickingId], {}
            );
            if (result && result.error) {
                this.notification.add("Lỗi đối chiếu với MISA: " + result.error, { type: "danger" });
                this.state.reconciliationOpen = false;
            } else {
                this.state.reconciliation = result;
            }
        } catch (e) {
            this.notification.add("Lỗi đối chiếu với MISA: " + (e.message || e), { type: "danger" });
            this.state.reconciliationOpen = false;
        }
        this.state.reconciliationLoading = false;
    }

    /** Bấm vào link 1 phiếu khác từ bên trong 1 drawer (VD "phiếu gốc"/"phiếu đi kèm") —
     * mở drawer của phiếu đó luôn thay vì rời trang sang form Odoo. */
    async openPickingDrawer(pickingId) {
        try {
            const row = await this.orm.call("stock.picking", "get_misa_invoice_picking_row", [pickingId], {});
            if (row) {
                await this.openDrawer(row);
            }
        } catch (e) {
            this.notification.add("Lỗi mở phiếu: " + (e.message || e), { type: "danger" });
        }
    }

    closeDrawer() {
        this.state.drawerOpen = false;
        this.state.drawerPicking = null;
        this.state.drawerLines = [];
        this.state.drawerSiblings = [];
        this.state.reconciliation = null;
        this.state.reconciliationOpen = false;
    }

    /** Mở wizard nhập lý do (dialog) — nạp lại drawer + số liệu tổng quan sau khi đóng
     * wizard (dù xác nhận hay hủy, vì không biết chắc kết quả — nạp lại luôn cho chắc). */
    async markException(pickingId) {
        try {
            const action = await this.orm.call("stock.picking", "action_mark_misa_invoice_exception", [[pickingId]], {});
            this.action.doAction(action, { onClose: () => this._refreshAfterException(pickingId) });
        } catch (e) {
            this.notification.add("Lỗi mở hộp thoại ngoại lệ: " + (e.message || e), { type: "danger" });
        }
    }

    async unmarkException(pickingId) {
        try {
            await this.orm.call("stock.picking", "action_unmark_misa_invoice_exception", [[pickingId]], {});
            this.notification.add("Đã bỏ đánh dấu ngoại lệ.", { type: "success" });
            await this._refreshAfterException(pickingId);
        } catch (e) {
            this.notification.add("Lỗi bỏ ngoại lệ: " + (e.message || e), { type: "danger" });
        }
    }

    async _refreshAfterException(pickingId) {
        if (this.state.drawerOpen && this.state.drawerPicking && this.state.drawerPicking.id === pickingId) {
            const row = await this.orm.call("stock.picking", "get_misa_invoice_picking_row", [pickingId], {});
            if (row) {
                this.state.drawerPicking = row;
            }
        }
        await this._reload();
    }

    /** Mở wizard gắn mã đề nghị MISA thủ công cho 1 phiếu (trường hợp sale quên ghi đúng số
     * phiếu xuất kho lúc tạo đề nghị trên MISA) — cùng pattern doAction+onClose refresh với
     * markException. */
    async openManualLinkWizard(pickingId) {
        try {
            const action = await this.orm.call("stock.picking", "action_open_misa_invoice_manual_link_wizard", [[pickingId]], {});
            this.action.doAction(action, { onClose: () => this._refreshAfterException(pickingId) });
        } catch (e) {
            this.notification.add("Lỗi mở hộp thoại gắn mã đề nghị: " + (e.message || e), { type: "danger" });
        }
    }

    /** Như openManualLinkWizard nhưng gọi từ drawer đơn hàng — chưa biết trước phiếu nào,
     * wizard tự giới hạn lựa chọn trong các phiếu của đúng đơn hàng đang xem. */
    async openManualLinkWizardForOrder() {
        const row = this.state.orderDrawerRow;
        if (!row) {
            return;
        }
        try {
            const action = await this.orm.call("stock.picking", "action_open_misa_invoice_manual_link_wizard_for_order", [row.id], {});
            this.action.doAction(action, { onClose: () => this._refreshAfterOrderException(row.id) });
        } catch (e) {
            this.notification.add("Lỗi mở hộp thoại gắn mã đề nghị: " + (e.message || e), { type: "danger" });
        }
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
                    search: this.state.pickingsTab.search || false,
                    state: this.state.pickingsTab.stateFilter || false,
                    saler_code: this.state.pickingsTab.salerFilter || false,
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

    onPickingsSearchInput(ev) {
        this.state.pickingsTab.searchDraft = ev.target.value;
    }

    onPickingsSearchKeydown(ev) {
        if (ev.key === "Enter") {
            this.submitPickingsSearch();
        }
    }

    submitPickingsSearch() {
        this.state.pickingsTab.search = this.state.pickingsTab.searchDraft.trim();
        this.loadPickingsTab(1);
    }

    clearPickingsSearch() {
        this.state.pickingsTab.search = "";
        this.state.pickingsTab.searchDraft = "";
        this.loadPickingsTab(1);
    }

    onPickingsStateFilterChange(ev) {
        this.state.pickingsTab.stateFilter = ev.target.value || "";
        this.loadPickingsTab(1);
    }

    onPickingsSalerFilterChange(ev) {
        this.state.pickingsTab.salerFilter = ev.target.value || "";
        this.loadPickingsTab(1);
    }

    async exportPickingsExcel() {
        try {
            const attachmentId = await this.orm.call(
                "stock.picking", "export_misa_invoice_picking_list_excel", [],
                {
                    search: this.state.pickingsTab.search || false,
                    state: this.state.pickingsTab.stateFilter || false,
                    saler_code: this.state.pickingsTab.salerFilter || false,
                    ...this.filterParams,
                }
            );
            window.location.href = "/web/content/" + attachmentId + "?download=true";
        } catch (e) {
            this.notification.add("Lỗi xuất Excel: " + (e.message || e), { type: "danger" });
        }
    }

    // ===== Tab "Đơn Shopee" (hóa đơn điện tử meInvoice riêng, amis_callback, chỉ xem) =====
    async loadShopeeTab(page) {
        this.state.shopeeTab.loading = true;
        try {
            const resp = await this.orm.call(
                "stock.picking", "get_misa_invoice_shopee_list", [],
                {
                    limit: this.state.shopeeTab.pageSize,
                    offset: (page - 1) * this.state.shopeeTab.pageSize,
                    search: this.state.shopeeTab.search || false,
                    state: this.state.shopeeTab.stateFilter || false,
                    date_from: this.state.shipFrom || false,
                    date_to: this.state.shipTo || false,
                }
            );
            this.state.shopeeTab.rows = resp.rows;
            this.state.shopeeTab.total = resp.total;
            this.state.shopeeTab.page = page;
        } catch (e) {
            this.notification.add("Lỗi tải danh sách đơn Shopee: " + (e.message || e), { type: "danger" });
        }
        this.state.shopeeTab.loading = false;
    }

    get shopeeTabTotalPages() {
        return Math.max(1, Math.ceil(this.state.shopeeTab.total / this.state.shopeeTab.pageSize));
    }

    shopeeTabPrevPage() {
        if (this.state.shopeeTab.page > 1) {
            this.loadShopeeTab(this.state.shopeeTab.page - 1);
        }
    }

    shopeeTabNextPage() {
        if (this.state.shopeeTab.page < this.shopeeTabTotalPages) {
            this.loadShopeeTab(this.state.shopeeTab.page + 1);
        }
    }

    onShopeeSearchInput(ev) {
        this.state.shopeeTab.searchDraft = ev.target.value;
    }

    onShopeeSearchKeydown(ev) {
        if (ev.key === "Enter") {
            this.submitShopeeSearch();
        }
    }

    submitShopeeSearch() {
        this.state.shopeeTab.search = this.state.shopeeTab.searchDraft.trim();
        this.loadShopeeTab(1);
    }

    clearShopeeSearch() {
        this.state.shopeeTab.search = "";
        this.state.shopeeTab.searchDraft = "";
        this.loadShopeeTab(1);
    }

    onShopeeStateFilterChange(ev) {
        this.state.shopeeTab.stateFilter = ev.target.value || "";
        this.loadShopeeTab(1);
    }

    // ===== Tab "Đơn hải quan" (hóa đơn MISA xuất TRƯỚC khi có phiếu xuất kho Odoo) =====
    get customsUnmatchedCount() {
        const preview = this.state.customsTab.preview;
        if (!preview) {
            return 0;
        }
        return preview.lines.filter((line) => !line.sale_order_found).length;
    }

    onCustomsInvInput(ev) {
        this.state.customsTab.invInput = ev.target.value;
    }

    async fetchCustomsInvoice() {
        const invNo = (this.state.customsTab.invInput || "").trim();
        if (!invNo) {
            this.notification.add("Vui lòng nhập số hóa đơn.", { type: "danger" });
            return;
        }
        this.state.customsTab.fetching = true;
        try {
            this.state.customsTab.preview = await this.orm.call(
                "stock.picking", "fetch_misa_customs_invoice", [invNo], {}
            );
        } catch (e) {
            this.notification.add("Lỗi tra cứu hóa đơn: " + (e.message || e), { type: "danger" });
        }
        this.state.customsTab.fetching = false;
    }

    cancelCustomsPreview() {
        this.state.customsTab.preview = null;
        this.state.customsTab.invInput = "";
    }

    async saveCustomsInvoice() {
        if (!this.state.customsTab.preview) {
            return;
        }
        const invNo = this.state.customsTab.preview.invoice_no;
        this.state.customsTab.saving = true;
        try {
            const result = await this.orm.call("stock.picking", "save_misa_customs_invoice", [invNo], {});
            this.notification.add(
                "Đã ghi nhận " + result.count + " dòng cho hóa đơn " + result.invoice_no + ".",
                { type: "success" }
            );
            this.state.customsTab.preview = null;
            this.state.customsTab.invInput = "";
            await this.loadCustomsTab(1);
        } catch (e) {
            this.notification.add("Lỗi ghi nhận hóa đơn: " + (e.message || e), { type: "danger" });
        }
        this.state.customsTab.saving = false;
    }

    async loadCustomsTab(page) {
        this.state.customsTab.loading = true;
        try {
            const resp = await this.orm.call(
                "stock.picking", "get_misa_customs_lines", [],
                {
                    limit: this.state.customsTab.pageSize,
                    offset: (page - 1) * this.state.customsTab.pageSize,
                    search: this.state.customsTab.search || false,
                }
            );
            this.state.customsTab.rows = resp.rows;
            this.state.customsTab.total = resp.total;
            this.state.customsTab.page = page;
        } catch (e) {
            this.notification.add("Lỗi tải danh sách đơn hải quan: " + (e.message || e), { type: "danger" });
        }
        this.state.customsTab.loading = false;
    }

    get customsTabTotalPages() {
        return Math.max(1, Math.ceil(this.state.customsTab.total / this.state.customsTab.pageSize));
    }

    customsTabPrevPage() {
        if (this.state.customsTab.page > 1) {
            this.loadCustomsTab(this.state.customsTab.page - 1);
        }
    }

    customsTabNextPage() {
        if (this.state.customsTab.page < this.customsTabTotalPages) {
            this.loadCustomsTab(this.state.customsTab.page + 1);
        }
    }

    onCustomsSearchInput(ev) {
        this.state.customsTab.searchDraft = ev.target.value;
    }

    onCustomsSearchKeydown(ev) {
        if (ev.key === "Enter") {
            this.submitCustomsSearch();
        }
    }

    submitCustomsSearch() {
        this.state.customsTab.search = this.state.customsTab.searchDraft.trim();
        this.loadCustomsTab(1);
    }

    clearCustomsSearch() {
        this.state.customsTab.search = "";
        this.state.customsTab.searchDraft = "";
        this.loadCustomsTab(1);
    }

    async deleteCustomsInvoice(invNo) {
        if (!window.confirm('Xóa toàn bộ dữ liệu đã ghi nhận cho hóa đơn "' + invNo + '"?')) {
            return;
        }
        try {
            await this.orm.call("stock.picking", "delete_misa_customs_invoice", [invNo], {});
            this.notification.add("Đã xóa hóa đơn " + invNo + ".", { type: "success" });
            await this.loadCustomsTab(this.state.customsTab.page);
        } catch (e) {
            this.notification.add("Lỗi xóa: " + (e.message || e), { type: "danger" });
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
                    state: this.state.ordersTab.stateFilter || false,
                    saler_code: this.state.ordersTab.salerFilter || false,
                    multi_request: this.state.ordersTab.multiRequestOnly,
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

    onOrdersStateFilterChange(ev) {
        this.state.ordersTab.stateFilter = ev.target.value || "";
        this.loadOrdersTab(1);
    }

    onOrdersSalerFilterChange(ev) {
        this.state.ordersTab.salerFilter = ev.target.value || "";
        this.loadOrdersTab(1);
    }

    onOrdersMultiRequestToggle(ev) {
        this.state.ordersTab.multiRequestOnly = ev.target.checked;
        this.loadOrdersTab(1);
    }

    async exportOrdersExcel() {
        try {
            const attachmentId = await this.orm.call(
                "stock.picking", "export_misa_invoice_order_list_excel", [],
                {
                    search: this.state.ordersTab.search || false,
                    state: this.state.ordersTab.stateFilter || false,
                    saler_code: this.state.ordersTab.salerFilter || false,
                    multi_request: this.state.ordersTab.multiRequestOnly,
                    ...this.filterParams,
                }
            );
            window.location.href = "/web/content/" + attachmentId + "?download=true";
        } catch (e) {
            this.notification.add("Lỗi xuất Excel: " + (e.message || e), { type: "danger" });
        }
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

    /** Bấm "Kiểm tra MISA ngay" trong drawer đơn hàng — lấy TẤT CẢ phiếu xuất kho (đã done)
     * của đúng đơn hàng đang xem rồi kiểm tra luôn, không cần tìm/chọn từng phiếu riêng lẻ. */
    async checkOrderNow() {
        const row = this.state.orderDrawerRow;
        if (!row || this.state.orderCheckLoading) {
            return;
        }
        this.state.orderCheckLoading = true;
        try {
            const resp = await this.orm.call("stock.picking", "action_check_misa_invoice_order", [row.id], {});
            if (!resp.count) {
                this.notification.add("Đơn hàng này không có phiếu xuất kho nào đã hoàn tất để kiểm tra.", { type: "warning" });
            } else {
                this.notification.add(`Đã kiểm tra xong ${resp.count} phiếu xuất kho của đơn hàng.`, { type: "success" });
            }
            await this._reload();
            const updated = this.state.ordersTab.rows.find((r) => r.id === row.id);
            if (updated) {
                this.state.orderDrawerRow = updated;
            }
        } catch (e) {
            this.notification.add("Lỗi kiểm tra MISA: " + (e.message || e), { type: "danger" });
        }
        this.state.orderCheckLoading = false;
    }

    /** Đánh dấu ngoại lệ cho TẤT CẢ phiếu (đã done, chưa ngoại lệ) của đơn hàng đang xem —
     * cùng pattern với markException/unmarkException ở drawer phiếu. */
    async markOrderException() {
        const row = this.state.orderDrawerRow;
        if (!row) {
            return;
        }
        try {
            const action = await this.orm.call("stock.picking", "action_mark_misa_invoice_exception_for_order", [row.id], {});
            this.action.doAction(action, { onClose: () => this._refreshAfterOrderException(row.id) });
        } catch (e) {
            this.notification.add("Lỗi mở hộp thoại ngoại lệ: " + (e.message || e), { type: "danger" });
        }
    }

    async unmarkOrderException() {
        const row = this.state.orderDrawerRow;
        if (!row) {
            return;
        }
        try {
            await this.orm.call("stock.picking", "action_unmark_misa_invoice_exception_for_order", [row.id], {});
            this.notification.add("Đã bỏ đánh dấu ngoại lệ.", { type: "success" });
            await this._refreshAfterOrderException(row.id);
        } catch (e) {
            this.notification.add("Lỗi bỏ ngoại lệ: " + (e.message || e), { type: "danger" });
        }
    }

    async _refreshAfterOrderException(orderId) {
        await this._reload();
        const updated = this.state.ordersTab.rows.find((r) => r.id === orderId);
        if (updated && this.state.orderDrawerOpen) {
            this.state.orderDrawerRow = updated;
        }
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

    formatCurrencyShort(num) {
        if (!num) {
            return "0";
        }
        const abs = Math.abs(num);
        if (abs >= 1e9) {
            return (num / 1e9).toLocaleString("vi-VN", { maximumFractionDigits: 1 }) + " tỷ";
        }
        if (abs >= 1e6) {
            return (num / 1e6).toLocaleString("vi-VN", { maximumFractionDigits: 1 }) + " tr";
        }
        if (abs >= 1e3) {
            return (num / 1e3).toLocaleString("vi-VN", { maximumFractionDigits: 0 }) + " k";
        }
        return Number(num).toLocaleString("vi-VN", { maximumFractionDigits: 0 });
    }

    // "Nice" trần trục Y (làm tròn lên 1/2/5x10^n) để lưới trục không lẻ số.
    _niceChartMax(raw) {
        if (raw <= 0) {
            return 1;
        }
        const exp = Math.floor(Math.log10(raw));
        const base = Math.pow(10, exp);
        const fraction = raw / base;
        let niceFraction = 10;
        if (fraction <= 1) {
            niceFraction = 1;
        } else if (fraction <= 2) {
            niceFraction = 2;
        } else if (fraction <= 5) {
            niceFraction = 5;
        }
        return niceFraction * base;
    }

    // Dựng hình học SVG dùng chung cho mọi biểu đồ cột+đường của dashboard (cùng 1 trục giá
    // trị, không dual-axis) — tham số hoá field lấy giá trị cột/đường/nhãn + hàm format trục.
    _buildComboChart(rows, { barField, lineField, labelField, formatAxis }) {
        if (!rows || !rows.length) {
            return null;
        }
        const width = 760;
        const height = 260;
        const padding = { top: 16, right: 16, bottom: 30, left: 60 };
        const plotW = width - padding.left - padding.right;
        const plotH = height - padding.top - padding.bottom;
        const baselineY = padding.top + plotH;

        const maxRaw = Math.max(1, ...rows.map((r) => Math.max(r[barField] || 0, r[lineField] || 0)));
        const niceMax = this._niceChartMax(maxRaw);

        const n = rows.length;
        const slotW = plotW / n;
        const barWidth = Math.max(4, Math.min(24, slotW * 0.5));
        const xCenter = (i) => padding.left + slotW * i + slotW / 2;
        const yFor = (v) => baselineY - (Math.min(v, niceMax) / niceMax) * plotH;

        const bars = rows.map((row, i) => {
            const y = yFor(row[barField] || 0);
            return {
                key: `bar-${i}`,
                x: xCenter(i) - barWidth / 2,
                y,
                width: barWidth,
                height: Math.max(0, baselineY - y),
                label: row[labelField],
                value: row[barField] || 0,
                row,
            };
        });

        const points = rows.map((row, i) => ({
            key: `pt-${i}`,
            x: xCenter(i),
            y: yFor(row[lineField] || 0),
            label: row[labelField],
            value: row[lineField] || 0,
            row,
        }));
        const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");

        const gridLines = [0, 0.25, 0.5, 0.75, 1].map((frac) => ({
            key: `grid-${frac}`,
            y: baselineY - frac * plotH,
            label: formatAxis(niceMax * frac),
        }));

        const labelEvery = Math.max(1, Math.ceil(n / 10));
        const xLabels = rows
            .map((row, i) => ({ key: `xl-${i}`, x: xCenter(i), label: row[labelField], show: i % labelEvery === 0 || i === n - 1 }))
            .filter((xl) => xl.show);

        return { width, height, padding, baselineY, bars, points, linePath, gridLines, xLabels };
    }

    // Tab "Theo ngày": cột = tổng tiền xuất kho, đường = tổng tiền đã xuất HĐ.
    get dailyChart() {
        return this._buildComboChart(this.state.dailyTab.rows, {
            barField: "actual_amount",
            lineField: "invoice_amount",
            labelField: "label",
            formatAxis: (v) => this.formatCurrencyShort(v),
        });
    }

    // Khu vực tổng quan: cột = tổng số phiếu theo nhân viên sale, đường = số phiếu đã xuất HĐ
    // theo nhân viên sale (cùng đơn vị "số phiếu" nên chung 1 trục được, bổ sung cho donut
    // vốn chỉ thấy tỷ lệ tổng thể chứ không thấy sale nào đang tồn đọng nhiều). Giới hạn
    // top 15 theo số lượng phiếu để cột không bị dày đặc khi có nhiều nhân viên sale.
    get salerChart() {
        const allRows = (this.state.data && this.state.data.by_saler) || [];
        const rows = [...allRows].sort((a, b) => b.total - a.total).slice(0, 15);
        return this._buildComboChart(rows, {
            barField: "total",
            lineField: "invoiced",
            labelField: "saler_code",
            formatAxis: (v) => Math.round(v).toLocaleString("vi-VN"),
        });
    }

    get salerChartTruncated() {
        return ((this.state.data && this.state.data.by_saler) || []).length > 15;
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
