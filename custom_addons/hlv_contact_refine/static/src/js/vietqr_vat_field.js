/** @odoo-module **/

import { useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { CharField, charField } from "@web/views/fields/char/char_field";


export class HlvVietqrVatField extends CharField {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({ loading: false });
    }

    get showLookupButton() {
        const record = this.props.record;
        return (
            record.isNew
            && !this.props.readonly
        );
    }

    async lookupBusiness() {
        if (this.state.loading) {
            return;
        }
        const taxCode = (
            this.input.el?.value
            || this.props.record.data[this.props.name]
            || ""
        ).trim();
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

HlvVietqrVatField.template = "hlv_contact_refine.HlvVietqrVatField";
HlvVietqrVatField.props = {
    ...CharField.props,
};

registry.category("fields").add("hlv_vietqr_vat", {
    ...charField,
    component: HlvVietqrVatField,
});
