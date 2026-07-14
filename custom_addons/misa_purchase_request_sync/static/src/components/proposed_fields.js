/** @odoo-module **/
import { registry } from "@web/core/registry";
import { FloatField, floatField } from "@web/views/fields/float/float_field";
import { Many2OneField, many2OneField } from "@web/views/fields/many2one/many2one_field";

export class FloatWithProposedField extends FloatField {
    get proposedValue() {
        const proposedField = this.props.options?.proposed_field;
        if (!proposedField) return null;
        
        const val = this.props.record.data[proposedField];
        if (typeof val === 'number') {
            return val.toLocaleString('vi-VN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }
        return val || "";
    }
}
FloatWithProposedField.template = "misa_purchase_request_sync.FloatWithProposedField";
FloatWithProposedField.props = {
    ...FloatField.props,
    options: { type: Object, optional: true },
};

export class Many2oneWithProposedField extends Many2OneField {
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
