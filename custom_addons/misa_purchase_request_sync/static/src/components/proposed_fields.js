/** @odoo-module **/
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { FloatField, floatField } from "@web/views/fields/float/float_field";
import { Many2OneField, many2OneField } from "@web/views/fields/many2one/many2one_field";
import { CharField, charField } from "@web/views/fields/char/char_field";
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
        const resModel = this.props.record.resModel;
        const resId = this.props.record.resId;
        const productData = this.props.record.data.product_id;
        if (!productData) return;

        let lineIdInt = false;
        if (resModel === 'purchase.request.line') {
            if (typeof resId === 'number' && resId > 0) {
                lineIdInt = resId;
            }
        } else {
            const lineData = this.props.record.data.line_id;
            if (lineData) {
                if (Array.isArray(lineData)) {
                    lineIdInt = lineData[0];
                } else if (lineData && typeof lineData === 'object') {
                    lineIdInt = lineData.resId || lineData.id || false;
                } else if (typeof lineData === 'number') {
                    lineIdInt = lineData;
                }
            }
        }

        if (!lineIdInt || (typeof lineIdInt === 'string' && lineIdInt.startsWith('virtual_'))) {
            return;
        }

        const action = await this.orm.call(
            "purchase.request.line",
            "action_view_price_history",
            [[lineIdInt]]
        );
        if (action) {
            if (!action.views && action.view_mode) {
                action.views = action.view_mode.split(',').map(mode => [false, mode.trim()]);
            }
            if (resModel === 'purchase.request.line.make.purchase.order.item' && typeof resId === 'number' && resId > 0) {
                action.context = { ...(action.context || {}), active_make_order_item_id: resId };
            }
            this.action.doAction(action);
        }
    }

    onDummy(event) {
        event.stopPropagation();
        event.preventDefault();
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
        const jsonStr = this.props.record.data.misa_new_supplier_json;
        if (!jsonStr) return;

        let data;
        try {
            data = JSON.parse(jsonStr);
        } catch (e) {
            return;
        }

        const context = {
            default_name: data.name || '',
            default_phone: data.phone || '',
            default_street: data.address || '',
            default_vat: data.vat || '',
            default_supplier_rank: 1,
            default_is_company: true,
            default_company_type: 'company',
            default_hlv_business_role: 'supplier',
        };

        const resModel = this.props.record.resModel;
        const resId = this.props.record.resId;

        if (resModel === 'purchase.request.line') {
            if (typeof resId === 'number' && resId > 0) {
                context.link_to_pr_line_id = resId;
            }
        } else {
            const lineData = this.props.record.data.line_id;
            if (lineData) {
                let lineIdInt = false;
                if (Array.isArray(lineData)) {
                    lineIdInt = lineData[0];
                } else if (lineData && typeof lineData === 'object') {
                    lineIdInt = lineData.resId || lineData.id || false;
                } else if (typeof lineData === 'number') {
                    lineIdInt = lineData;
                }
                if (lineIdInt && !(typeof lineIdInt === 'string' && lineIdInt.startsWith('virtual_'))) {
                    context.link_to_pr_line_id = lineIdInt;
                }
            }
            if (typeof resId === 'number' && resId > 0) {
                context.link_to_pr_wizard_item_id = resId;
            }
        }

        await this.action.doAction({
            type: 'ir.actions.act_window',
            name: `Tạo NCC – ${data.name || ''}`,
            res_model: 'res.partner',
            view_mode: 'form',
            views: [[false, 'form']],
            target: 'new',
            context: context,
        });
    }

    onDummy(event) {
        event.stopPropagation();
        event.preventDefault();
    }
}
Many2oneWithProposedField.template = "misa_purchase_request_sync.Many2oneWithProposedField";
Many2oneWithProposedField.props = {
    ...Many2OneField.props,
    options: { type: Object, optional: true },
};

export class ProductTwoLinesField extends Many2OneField {
    get codeAndName() {
        const val = this.props.record.data[this.props.name];
        if (!val) return { code: "", name: "" };
        
        const displayName = Array.isArray(val) ? val[1] : (val.displayName || val.name || "");
        const match = displayName.match(/^\[(.*?)\]\s*(.*)$/);
        if (match) {
            return {
                code: `[${match[1]}]`,
                name: match[2]
            };
        }
        return {
            code: "",
            name: displayName
        };
    }
}
ProductTwoLinesField.template = "misa_purchase_request_sync.ProductTwoLinesField";
ProductTwoLinesField.props = {
    ...Many2OneField.props,
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

registry.category("fields").add("product_two_lines", {
    ...many2OneField,
    component: ProductTwoLinesField,
});


