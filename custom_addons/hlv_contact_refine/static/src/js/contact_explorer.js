/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class HlvContactExplorer extends Component {
    static template = "hlv_contact_refine.ContactExplorer";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            search: "",
            role: "all",
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
            120,
        ]);
        this.state.rows = data.rows || [];
        this.state.selected = data.selected || false;
        this.state.related = data.related || [];
        this.state.roles = data.roles || [];
        this.state.loading = false;
    }

    async selectPartner(partnerId) {
        const data = await this.orm.call("res.partner", "hlv_contact_explorer_select", [partnerId]);
        this.state.selected = data.selected || false;
        this.state.related = data.related || [];
    }

    async setRole(role) {
        this.state.role = role;
        await this.load();
    }

    async onSearch(ev) {
        this.state.search = ev.target.value || "";
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
}

registry.category("actions").add("hlv_contact_explorer_action", HlvContactExplorer);
