/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PartnerLine } from "@point_of_sale/app/screens/partner_list/partner_line/partner_line";
import { useService } from "@web/core/utils/hooks";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { usePos } from "@point_of_sale/app/store/pos_hook";

patch(PartnerLine.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.pos = usePos();
    },

    getCustomerTypeName() {
        const partner = this.props.partner;
        if (!partner.pos_customer_type) return null;

        // pos_customer_type is now [id, name] or just id
        const typeId = Array.isArray(partner.pos_customer_type)
            ? partner.pos_customer_type[0]
            : partner.pos_customer_type;

        // Find in loaded data
        const customerTypes = this.pos.data?.models?.['pos.customer.type']?.records ||
            this.pos.models?.['pos.customer.type']?.getAll?.() || [];

        const typeRecord = customerTypes.find(t => t.id === typeId);
        return typeRecord ? typeRecord.name : null;
    },

    getCustomerTypeColor() {
        const partner = this.props.partner;
        if (!partner.pos_customer_type) return 'secondary';

        const typeId = Array.isArray(partner.pos_customer_type)
            ? partner.pos_customer_type[0]
            : partner.pos_customer_type;

        const customerTypes = this.pos.data?.models?.['pos.customer.type']?.records ||
            this.pos.models?.['pos.customer.type']?.getAll?.() || [];

        const typeRecord = customerTypes.find(t => t.id === typeId);
        return typeRecord?.color || 'info';
    },

    async onToggleCustomerType(ev) {
        ev.stopPropagation(); // Avoid selecting the partner row

        const partner = this.props.partner;

        // Build selection list dynamically from loaded customer types
        const customerTypes = this.pos.data?.models?.['pos.customer.type']?.records ||
            this.pos.models?.['pos.customer.type']?.getAll?.() || [];

        const selectionList = customerTypes.map(type => ({
            id: type.id,
            label: type.name,
            item: type.id,
        }));

        // Add "clear" option
        selectionList.push({ id: 'false', label: 'Bỏ chọn', item: false });

        try {
            const selectedItem = await makeAwaitable(this.dialog, SelectionPopup, {
                title: 'Chọn loại khách hàng',
                list: selectionList,
            });

            if (selectedItem !== undefined && selectedItem !== null) {
                const newTypeId = selectedItem;

                // Get current type id for comparison
                const currentTypeId = Array.isArray(partner.pos_customer_type)
                    ? partner.pos_customer_type[0]
                    : partner.pos_customer_type;

                if (newTypeId === currentTypeId) {
                    return;
                }

                // Optimistic update - find the type record for display
                if (newTypeId) {
                    const typeRecord = customerTypes.find(t => t.id === newTypeId);
                    partner.pos_customer_type = typeRecord ? [typeRecord.id, typeRecord.name] : newTypeId;
                } else {
                    partner.pos_customer_type = false;
                }

                // Backend update
                await this.orm.write("res.partner", [partner.id], {
                    pos_customer_type: newTypeId || false
                });

                console.log(`[HLV] Set partner ${partner.name} type to ${newTypeId}`);
            }

        } catch (error) {
            console.log("[HLV] Selection cancelled or failed", error);
        }
    }
});

