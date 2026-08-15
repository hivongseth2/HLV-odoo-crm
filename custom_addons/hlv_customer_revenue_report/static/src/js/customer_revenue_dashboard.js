/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

const MODEL = "hlv.customer.revenue.report";

export class CustomerRevenueDashboard extends Component {
    static template = "hlv_customer_revenue_report.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            view: "list", // "list" | "detail"
            searchTerm: "",
            dateFrom: "",
            dateTo: "",
            shopeeFilter: "all", // "all" | "shopee" | "non_shopee"
            isLoading: false,

            customers: [],
            sortField: "amount_net",
            sortDir: "desc",

            selectedGroupType: null, // "partner" | "shop"
            selectedGroupId: null,
            selectedGroupLabel: "",
            selectedIsShopee: false,
            months: [],

            drawerOpen: false,
            drawerMonth: null,
            drawerLoading: false,
            drawerRows: [],
        });
        this._searchTimer = null;

        onWillStart(async () => {
            await this.loadCustomers();
        });
    }

    // ==================== Danh sách khách hàng / shop Shopee ====================
    async loadCustomers() {
        this.state.isLoading = true;
        try {
            this.state.customers = await this.orm.call(MODEL, "get_customers_summary", [], {
                date_from: this.state.dateFrom || false,
                date_to: this.state.dateTo || false,
                search: this.state.searchTerm || false,
                shopee_filter: this.state.shopeeFilter,
            });
        } catch (e) {
            this.notification.add("Lỗi tải danh sách khách hàng: " + (e.message || e), { type: "danger" });
            this.state.customers = [];
        }
        this.state.isLoading = false;
    }

    onSearchInput(ev) {
        this.state.searchTerm = ev.target.value;
        if (this._searchTimer) {
            clearTimeout(this._searchTimer);
        }
        this._searchTimer = setTimeout(() => this.loadCustomers(), 300);
    }

    onShopeeFilterChange() {
        this.loadCustomers();
    }

    onDateChange() {
        if (this.state.view === "detail") {
            this.loadMonthly();
        } else {
            this.loadCustomers();
        }
    }

    toggleSort(field) {
        if (this.state.sortField === field) {
            this.state.sortDir = this.state.sortDir === "asc" ? "desc" : "asc";
        } else {
            this.state.sortField = field;
            this.state.sortDir = field === "group_label" ? "asc" : "desc";
        }
    }

    get sortedCustomers() {
        const rows = this.state.customers.slice();
        const field = this.state.sortField;
        const dir = this.state.sortDir === "asc" ? 1 : -1;
        rows.sort((a, b) => {
            const av = a[field];
            const bv = b[field];
            if (typeof av === "string") {
                return av.localeCompare(bv) * dir;
            }
            return (av - bv) * dir;
        });
        return rows;
    }

    selectCustomer(row) {
        this.state.view = "detail";
        this.state.selectedGroupType = row.group_type;
        this.state.selectedGroupId = row.group_id;
        this.state.selectedGroupLabel = row.group_label;
        this.state.selectedIsShopee = row.is_shopee_group;
        this.loadMonthly();
    }

    backToList() {
        this.state.view = "list";
        this.state.months = [];
        this.state.selectedGroupType = null;
        this.state.selectedGroupId = null;
        this.state.selectedGroupLabel = "";
    }

    // ==================== Doanh thu theo tháng (1 khách hàng / 1 shop) ====================
    async loadMonthly() {
        if (!this.state.selectedGroupId) {
            return;
        }
        this.state.isLoading = true;
        try {
            this.state.months = await this.orm.call(MODEL, "get_group_monthly_summary", [], {
                group_type: this.state.selectedGroupType,
                group_id: this.state.selectedGroupId,
                date_from: this.state.dateFrom || false,
                date_to: this.state.dateTo || false,
            });
        } catch (e) {
            this.notification.add("Lỗi tải doanh thu: " + (e.message || e), { type: "danger" });
            this.state.months = [];
        }
        this.state.isLoading = false;
    }

    get totals() {
        const t = {
            order_count: 0, qty_delivered: 0, qty_returned: 0, qty_net: 0,
            amount_gross: 0, amount_returned: 0, amount_net: 0,
        };
        for (const m of this.state.months) {
            t.order_count += m.order_count;
            t.qty_delivered += m.qty_delivered;
            t.qty_returned += m.qty_returned;
            t.qty_net += m.qty_net;
            t.amount_gross += m.amount_gross;
            t.amount_returned += m.amount_returned;
            t.amount_net += m.amount_net;
        }
        return t;
    }

    // ==================== Drawer chi tiết theo đơn hàng ====================
    async openMonthDrawer(month) {
        this.state.drawerOpen = true;
        this.state.drawerMonth = month;
        this.state.drawerRows = [];
        this.state.drawerLoading = true;
        try {
            this.state.drawerRows = await this.orm.call(MODEL, "get_group_month_detail", [], {
                group_type: this.state.selectedGroupType,
                group_id: this.state.selectedGroupId,
                date_from: month.date_from,
                date_to: month.date_to,
            });
        } catch (e) {
            this.notification.add("Lỗi tải chi tiết: " + (e.message || e), { type: "danger" });
        }
        this.state.drawerLoading = false;
    }

    closeDrawer() {
        this.state.drawerOpen = false;
        this.state.drawerMonth = null;
        this.state.drawerRows = [];
    }

    onDrawerOverlayClick(ev) {
        if (ev.target === ev.currentTarget) {
            this.closeDrawer();
        }
    }

    openSaleOrder(orderId) {
        if (!orderId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: orderId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ==================== Xuất Excel ====================
    async exportExcel() {
        try {
            let attachmentId;
            if (this.state.view === "detail" && this.state.selectedGroupId) {
                attachmentId = await this.orm.call(MODEL, "export_group_revenue_excel", [], {
                    group_type: this.state.selectedGroupType,
                    group_id: this.state.selectedGroupId,
                    date_from: this.state.dateFrom || false,
                    date_to: this.state.dateTo || false,
                });
            } else {
                attachmentId = await this.orm.call(MODEL, "export_customers_summary_excel", [], {
                    date_from: this.state.dateFrom || false,
                    date_to: this.state.dateTo || false,
                    search: this.state.searchTerm || false,
                    shopee_filter: this.state.shopeeFilter,
                });
            }
            window.location.href = "/web/content/" + attachmentId + "?download=true";
        } catch (e) {
            this.notification.add("Lỗi xuất Excel: " + (e.message || e), { type: "danger" });
        }
    }

    // ==================== Format ====================
    formatCurrency(value) {
        return Math.round(value || 0).toLocaleString("vi-VN");
    }

    formatNumber(value) {
        const v = value || 0;
        return Number.isInteger(v) ? v.toLocaleString("vi-VN") : v.toLocaleString("vi-VN", { maximumFractionDigits: 2 });
    }
}

registry.category("actions").add("hlv_customer_revenue_report.Dashboard", CustomerRevenueDashboard);
