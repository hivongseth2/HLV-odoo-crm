/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";


export class HlvVietqrLookupButton extends Component {
    static template = "hlv_contact_refine.HlvVietqrLookupButton";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({ loading: false });
    }

    get showLookupButton() {
        return this.props.record.isNew;
    }

    async lookupBusiness() {
        if (this.state.loading) {
            return;
        }
        const taxCode = String(this.props.record.data.vat || "").trim();
        if (!taxCode) {
            this.notification.add("Vui lòng nhập mã số thuế trước.", {
                type: "warning",
            });
            return;
        }

        this.state.loading = true;
        try {
            const business = await this.orm.call(
                "res.partner",
                "hlv_vietqr_lookup_business",
                [taxCode]
            );
            const changes = {
                name: business.name,
                vat: business.vat,
                street: business.street || false,
                company_type: "company",
                is_company: true,
            };
            if (business.country_id) {
                changes.country_id = [business.country_id, business.country_name];
            }
            await this.props.record.update(changes);

            const status = business.status ? ` — ${business.status}` : "";
            this.notification.add(`Đã lấy thông tin ${business.name}${status}.`, {
                type: "success",
            });
        } finally {
            this.state.loading = false;
        }
    }
}

registry.category("fields").add("hlv_vietqr_lookup_button", {
    component: HlvVietqrLookupButton,
    supportedTypes: ["boolean"],
});
