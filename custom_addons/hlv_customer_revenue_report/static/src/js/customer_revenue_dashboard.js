/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

const MODEL = "hlv.customer.revenue.report";

export class CustomerRevenueDashboard extends Component {
    static template = "hlv_customer_revenue_report.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            searchTerm: "",
            suggestions: [],
            showSuggestions: false,
            partnerId: null,
            partnerName: "",
            dateFrom: "",
            dateTo: "",
            isLoading: false,
            months: [],
            drawerOpen: false,
            drawerMonth: null,
            drawerLoading: false,
            drawerRows: [],
        });
        this._searchTimer = null;
    }

    // ==================== Tìm khách hàng ====================
    onSearchInput(ev) {
        const term = ev.target.value;
        this.state.searchTerm = term;
        this.state.partnerId = null;
        this.state.months = [];
        if (this._searchTimer) {
            clearTimeout(this._searchTimer);
        }
        if (!term || term.length < 2) {
            this.state.suggestions = [];
            this.state.showSuggestions = false;
            return;
        }
        this._searchTimer = setTimeout(() => this._fetchSuggestions(term), 300);
    }

    async _fetchSuggestions(term) {
        try {
            const result = await this.orm.call(MODEL, "search_report_customers", [], { term, limit: 20 });
            this.state.suggestions = result;
            this.state.showSuggestions = result.length > 0;
        } catch (e) {
            this.notification.add("Lỗi tìm khách hàng: " + (e.message || e), { type: "danger" });
        }
    }

    onSearchBlur() {
        // Trì hoãn để kịp xử lý click chọn gợi ý trước khi ẩn dropdown
        setTimeout(() => {
            this.state.showSuggestions = false;
        }, 200);
    }

    selectCustomer(item) {
        this.state.partnerId = item.id;
        this.state.partnerName = item.name;
        this.state.searchTerm = item.name;
        this.state.suggestions = [];
        this.state.showSuggestions = false;
        this.loadMonthly();
    }

    onDateChange() {
        if (this.state.partnerId) {
            this.loadMonthly();
        }
    }

    // ==================== Doanh thu theo tháng ====================
    async loadMonthly() {
        if (!this.state.partnerId) {
            return;
        }
        this.state.isLoading = true;
        try {
            this.state.months = await this.orm.call(MODEL, "get_customer_monthly_summary", [], {
                partner_id: this.state.partnerId,
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
            this.state.drawerRows = await this.orm.call(MODEL, "get_customer_month_detail", [], {
                partner_id: this.state.partnerId,
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
        if (!this.state.partnerId) {
            this.notification.add("Vui lòng chọn khách hàng trước khi xuất Excel.", { type: "warning" });
            return;
        }
        try {
            const attachmentId = await this.orm.call(MODEL, "export_customer_revenue_excel", [], {
                partner_id: this.state.partnerId,
                date_from: this.state.dateFrom || false,
                date_to: this.state.dateTo || false,
            });
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
