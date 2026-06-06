/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class HlvContactExplorer extends Component {
    static template = "hlv_contact_refine.ContactExplorer";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            search: "",
            role: "customer_crm",
            page: 1,
            pageSize: 80,
            total: 0,
            rows: [],
            selected: false,
            related: [],
            roles: [],
        });

        onWillStart(async () => {
            await this.load();
        });
    }

    async load() {
        this.state.loading = true;
        const data = await this.orm.call("res.partner", "hlv_contact_explorer_data", [
            this.state.search,
            this.state.role,
            this.state.pageSize,
            (this.state.page - 1) * this.state.pageSize,
        ]);
        this.state.rows = data.rows || [];
        this.state.selected = data.selected || false;
        this.state.related = data.related || [];
        this.state.roles = data.roles || [];
        this.state.total = data.total || 0;
        this.state.loading = false;
    }

    async selectPartner(partnerId) {
        const data = await this.orm.call("res.partner", "hlv_contact_explorer_select", [partnerId]);
        this.state.selected = data.selected || false;
        this.state.related = data.related || [];
    }

    async setRole(role) {
        this.state.role = role;
        this.state.page = 1;
        await this.load();
    }

    async onSearch(ev) {
        this.state.search = ev.target.value || "";
        this.state.page = 1;
        await this.load();
    }

    get pageCount() {
        return Math.max(1, Math.ceil(this.state.total / this.state.pageSize));
    }

    get pageStart() {
        if (!this.state.total) {
            return 0;
        }
        return (this.state.page - 1) * this.state.pageSize + 1;
    }

    get pageEnd() {
        return Math.min(this.state.total, this.state.page * this.state.pageSize);
    }

    async previousPage() {
        if (this.state.page <= 1) {
            return;
        }
        this.state.page -= 1;
        await this.load();
    }

    async nextPage() {
        if (this.state.page >= this.pageCount) {
            return;
        }
        this.state.page += 1;
        await this.load();
    }

    openPartner(partnerId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: partnerId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async fixPartnerData(partnerId) {
        const data = await this.orm.call("res.partner", "hlv_contact_explorer_fix_data", [partnerId]);
        const selectedId = data.selected && data.selected.id;
        this.state.selected = data.selected || false;
        this.state.related = data.related || [];
        this.notification.add(
            data.fixed_ids && data.fixed_ids.length
                ? `Đã sửa ${data.fixed_ids.length} liên hệ.`
                : "Không có mã cần sửa trên liên hệ này.",
            { type: "success" }
        );
        await this.load();
        if (selectedId) {
            await this.selectPartner(selectedId);
        }
    }
}

registry.category("actions").add("hlv_contact_explorer_action", HlvContactExplorer);
