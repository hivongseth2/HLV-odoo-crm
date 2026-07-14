/** @odoo-module **/
import { registry } from "@web/core/registry";
import { FloatField, floatField } from "@web/views/fields/float/float_field";
import { Many2OneField, many2OneField } from "@web/views/fields/many2one/many2one_field";
import { useService } from "@web/core/utils/hooks";

export class FloatWithProposedField extends FloatField {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.action = useService("action");
    }

    get proposedValue() {
        const proposedField = this.props.options?.proposed_field;
        if (!proposedField) return null;
        
        const val = this.props.record.data[proposedField];
        if (typeof val === 'number') {
            return val.toLocaleString('vi-VN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }
        return val || "";
    }

    get showPriceHistoryButton() {
        return (this.props.name === 'actual_price_unit' || this.props.name === 'misa_price_before_tax') && !!this.props.record.data.product_id;
    }

    async onViewPriceHistory() {
        const resId = this.props.record.resId;
        const resModel = this.props.record.resModel;
        const action = await this.orm.call(
            resModel,
            "action_view_price_history",
            [resId]
        );
        if (action) {
            this.action.doAction(action);
        }
    }
}
FloatWithProposedField.template = "misa_purchase_request_sync.FloatWithProposedField";
FloatWithProposedField.props = {
    ...FloatField.props,
    options: { type: Object, optional: true },
};

export class Many2oneWithProposedField extends Many2OneField {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.action = useService("action");
    }

    get proposedValue() {
        const proposedField = this.props.options?.proposed_field;
        if (!proposedField) return null;
        
        const val = this.props.record.data[proposedField];
        if (Array.isArray(val)) {
            return val[1];
        } else if (val && typeof val === 'object') {
            return val.displayName || val.name || "";
        }
        return val || "";
    }

    get showCreateSupplierButton() {
        if (this.props.name !== 'supplier_id' && this.props.name !== 'sale_proposed_supplier_id') return false;
        const val = this.props.record.data[this.props.name];
        if (val) return false;
        return !!this.props.record.data.misa_new_supplier_json;
    }

    async onCreateSupplier() {
        const resId = this.props.record.resId;
        const resModel = this.props.record.resModel;
        const methodName = resModel === 'purchase.request.line' ? "action_create_line_supplier" : "action_create_item_supplier";
        const action = await this.orm.call(resModel, methodName, [resId]);
        if (action) {
            this.action.doAction(action);
        }
    }
}
Many2oneWithProposedField.template = "misa_purchase_request_sync.Many2oneWithProposedField";
Many2oneWithProposedField.props = {
    ...Many2OneField.props,
    options: { type: Object, optional: true },
};

registry.category("fields").add("float_with_proposed", {
    ...floatField,
    component: FloatWithProposedField,
    extractProps: (fieldInfo, activeActions) => {
        const props = floatField.extractProps ? floatField.extractProps(fieldInfo, activeActions) : {};
        props.options = fieldInfo.options || fieldInfo.attrs?.options;
        return props;
    },
});

registry.category("fields").add("many2one_with_proposed", {
    ...many2OneField,
    component: Many2oneWithProposedField,
    extractProps: (fieldInfo, activeActions) => {
        const props = many2OneField.extractProps ? many2OneField.extractProps(fieldInfo, activeActions) : {};
        props.options = fieldInfo.options || fieldInfo.attrs?.options;
        return props;
    },
});
