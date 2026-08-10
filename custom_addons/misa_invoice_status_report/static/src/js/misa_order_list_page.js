/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

// Trùng với tập lựa chọn trạng thái ở dashboard chính (misa_invoice_dashboard.js) — không
// import chung được vì đó là module riêng, nhân đôi 1 mảng nhỏ còn rẻ hơn tách thêm file dùng
// chung chỉ để lấy 1 hằng số.
const PICKING_STATE_FILTER_OPTIONS = [
    { value: "not_checked", label: "Chưa kiểm tra" },
    { value: "missing", label: "Chưa có đề nghị xuất HĐ" },
    { value: "requested", label: "Đã đề nghị, chờ HĐ" },
    { value: "invoiced", label: "Đã xuất hóa đơn" },
];

/** Trang riêng "Danh sách đơn hàng" (khác dashboard Tổng quan) — mở từ nút "Xem tất cả đơn
 * hàng", KHÔNG giới hạn theo ngày (xem toàn bộ phạm vi đối soát), chỉ gồm: tìm kiếm/lọc +
 * bảng phân trang + drawer thể hiện quan hệ đơn hàng ↔ phiếu xuất kho khi bấm vào 1 dòng. */
export class MisaOrderListPage extends Component {
    static template = "misa_invoice_status_report.OrderListPage";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            isLoading: true,
            salerOptions: [],
            // Để trống = không giới hạn theo ngày (đúng nghĩa "xem tất cả" mặc định) — có thể
            // tự nhập để thu hẹp lại khi cần.
            shipFrom: "",
            shipTo: "",
            ordersTab: {
                rows: [], total: 0, page: 1, pageSize: 50, loading: false,
                search: "", searchDraft: "", stateFilter: "", salerFilter: "",
            },
            orderDrawerOpen: false,
            orderDrawerRow: null,
            orderCheckLoading: false,
        });

        onWillStart(async () => {
            await Promise.all([this.loadSalerOptions(), this.loadOrdersTab(1)]);
            this.state.isLoading = false;
        });
    }

    get pickingStateFilterOptions() {
        return PICKING_STATE_FILTER_OPTIONS;
    }

    async loadSalerOptions() {
        try {
            this.state.salerOptions = await this.orm.call("stock.picking", "get_misa_invoice_saler_options", [], {});
        } catch (e) {
            this.notification.add("Lỗi tải danh sách nhân viên sale: " + (e.message || e), { type: "danger" });
        }
    }

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
                    date_from: this.state.shipFrom || false,
                    date_to: this.state.shipTo || false,
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

    onShipFromChange(ev) {
        this.state.shipFrom = ev.target.value || "";
        this.loadOrdersTab(1);
    }

    onShipToChange(ev) {
        this.state.shipTo = ev.target.value || "";
        this.loadOrdersTab(1);
    }

    clearShipDateFilter() {
        this.state.shipFrom = "";
        this.state.shipTo = "";
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
                    date_from: this.state.shipFrom || false,
                    date_to: this.state.shipTo || false,
                }
            );
            window.location.href = "/web/content/" + attachmentId + "?download=true";
        } catch (e) {
            this.notification.add("Lỗi xuất Excel: " + (e.message || e), { type: "danger" });
        }
    }

    /** Bấm vào dòng đơn hàng: mở drawer chi tiết (dữ liệu đã có sẵn `pickings` con từ
     * backend, gồm cả ghi chú "gộp chung" với phiếu gốc) — nút trong drawer mở thẳng form
     * đơn bán trên Odoo. */
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
            await this.loadOrdersTab(this.state.ordersTab.page);
            const updated = this.state.ordersTab.rows.find((r) => r.id === row.id);
            if (updated) {
                this.state.orderDrawerRow = updated;
            }
        } catch (e) {
            this.notification.add("Lỗi kiểm tra MISA: " + (e.message || e), { type: "danger" });
        }
        this.state.orderCheckLoading = false;
    }

    /** Bấm vào link phiếu gốc/phiếu đi kèm bên trong drawer đơn hàng — mở form phiếu đó
     * (trang này không có drawer chi tiết phiếu riêng như dashboard Tổng quan, nên mở form
     * Odoo thẳng luôn, đơn giản hơn cho 1 trang chỉ tập trung vào ĐƠN HÀNG). */
    openPicking(pickingId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            res_id: pickingId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    formatCurrency(num) {
        if (!num) {
            return "0 ₫";
        }
        return Number(num).toLocaleString("vi-VN", { maximumFractionDigits: 0 }) + " ₫";
    }
}

registry.category("actions").add("misa_invoice_status_report.OrderListPage", MisaOrderListPage);
