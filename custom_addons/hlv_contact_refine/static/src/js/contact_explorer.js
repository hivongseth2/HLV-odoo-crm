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
            crmChecking: false,
            crmResult: false,
            mergeIds: [],
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
        this.state.crmResult = false;
        this.state.mergeIds = [];
        this.state.loading = false;
    }

    async selectPartner(partnerId) {
        const data = await this.orm.call("res.partner", "hlv_contact_explorer_select", [partnerId]);
        this.state.selected = data.selected || false;
        this.state.related = data.related || [];
        this.state.crmResult = false;
        if (this.state.selected) {
            this.state.mergeIds = this.state.mergeIds.filter((id) => id !== this.state.selected.id);
        }
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

    async fixVisibleDirty() {
        const partnerIds = this.state.rows.map((row) => row.id);
        if (!partnerIds.length) {
            return;
        }
        const data = await this.orm.call("res.partner", "hlv_contact_explorer_fix_many", [partnerIds]);
        this.notification.add(
            data.fixed_ids && data.fixed_ids.length
                ? `Đã sửa ${data.fixed_ids.length} liên hệ trên trang hiện tại.`
                : "Trang hiện tại không có lỗi mã cần sửa.",
            { type: "success" }
        );
        await this.load();
    }

    async compareCRM() {
        if (!this.state.selected) {
            return;
        }
        this.state.crmChecking = true;
        try {
            const data = await this.orm.call("res.partner", "hlv_contact_explorer_compare_crm", [
                this.state.selected.id,
            ]);
            this.state.crmResult = data;
            this.notification.add(data.message || "Đã đối chiếu CRM.", {
                type: data.ok ? "success" : "warning",
            });
        } finally {
            this.state.crmChecking = false;
        }
    }

    async applyCRMAccount(account) {
        if (!this.state.selected) {
            return;
        }
        const data = await this.orm.call("res.partner", "hlv_contact_explorer_apply_crm_account", [
            this.state.selected.id,
            account,
        ]);
        this.notification.add(data.message || "Đã cập nhật từ CRM.", {
            type: data.ok ? "success" : "warning",
        });
        if (data.selected) {
            this.state.selected = data.selected;
            this.state.related = data.related || [];
        }
        const selectedId = data.selected && data.selected.id;
        await this.load();
        if (selectedId) {
            await this.selectPartner(selectedId);
        }
    }

    toggleMerge(rowId, ev) {
        if (ev) {
            ev.stopPropagation();
        }
        if (this.state.selected && rowId === this.state.selected.id) {
            return;
        }
        if (this.state.mergeIds.includes(rowId)) {
            this.state.mergeIds = this.state.mergeIds.filter((id) => id !== rowId);
        } else {
            this.state.mergeIds = [...this.state.mergeIds, rowId];
        }
    }

    get mergeCount() {
        return this.state.mergeIds.length;
    }

    async openMergeWizard() {
        if (!this.state.selected || !this.state.mergeIds.length) {
            return;
        }
        const action = await this.orm.call("res.partner", "hlv_contact_explorer_merge_action", [
            this.state.selected.id,
            this.state.mergeIds,
        ]);
        if (action) {
            this.action.doAction(action);
        }
    }
}

registry.category("actions").add("hlv_contact_explorer_action", HlvContactExplorer);
