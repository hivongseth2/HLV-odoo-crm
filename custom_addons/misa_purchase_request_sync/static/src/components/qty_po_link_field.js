/** @odoo-module **/
import { Component, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { usePopover } from "@web/core/popover/popover_hook";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Dialog } from "@web/core/dialog/dialog";

function formatMisaFloat(val) {
    if (!val) {
        return "0";
    }
    const rounded = Math.round(val * 100) / 100;
    return rounded.toLocaleString('vi-VN', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

export class PoLinkTooltip extends Component {
    static template = "misa_purchase_request_sync.PoLinkTooltip";
    static props = {
        pos: Array,
    };

    formatQty(qty) {
        return formatMisaFloat(qty);
    }
}

export class PoLinkSelectDialog extends Component {
    static template = "misa_purchase_request_sync.PoLinkSelectDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        pos: Array,
        onSelect: Function,
    };

    formatQty(qty) {
        return formatMisaFloat(qty);
    }

    onSelectPo(po) {
        this.props.onSelect(po);
        this.props.close();
    }
}

export class QtyWithPoLinkField extends Component {
    static template = "misa_purchase_request_sync.QtyWithPoLinkField";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.badgeRef = useRef("badgeRef");
        this.popover = usePopover(PoLinkTooltip, {
            position: "bottom",
            closeOnClickAway: true,
        });
    }

    get qtyStr() {
        return formatMisaFloat(this.props.record.data.product_qty);
    }

    get purchasedQtyStr() {
        return formatMisaFloat(this.props.record.data.purchased_qty);
    }

    get hasPurchasedQty() {
        return !!this.props.record.data.purchased_qty;
    }

    get linkedPos() {
        const raw = this.props.record.data.misa_linked_po_json;
        if (!raw) {
            return [];
        }
        try {
            const data = JSON.parse(raw);
            return Array.isArray(data) ? data : [];
        } catch (e) {
            return [];
        }
    }

    onMouseEnterBadge() {
        const pos = this.linkedPos;
        if (!pos.length || this.popover.isOpen) {
            return;
        }
        this.popover.open(this.badgeRef.el, { pos });
    }

    onMouseLeaveBadge() {
        this.popover.close();
    }

    openPurchaseOrder(po) {
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'purchase.order',
            res_id: po.id,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    onClickBadge(ev) {
        ev.stopPropagation();
        ev.preventDefault();
        this.popover.close();
        const pos = this.linkedPos;
        if (!pos.length) {
            return;
        }
        if (pos.length === 1) {
            this.openPurchaseOrder(pos[0]);
            return;
        }
        this.dialog.add(PoLinkSelectDialog, {
            pos,
            onSelect: (po) => this.openPurchaseOrder(po),
        });
    }

    onDummy(ev) {
        ev.stopPropagation();
        ev.preventDefault();
    }
}

registry.category("fields").add("qty_po_link", {
    component: QtyWithPoLinkField,
});
