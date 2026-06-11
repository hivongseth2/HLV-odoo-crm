/** @odoo-module **/

import { Component } from "@odoo/owl";

export class Sidebar extends Component {
    static template = "hlv_barcode_shipper.Sidebar";
    static props = {
        isOpen: { type: Boolean, optional: true },
        activeTab: { type: String, optional: true },
        onClose: { type: Function, optional: true },
        onTabChange: { type: Function, optional: true },
    };

    onTabClick(tabName) {
        if (this.props.onTabChange) {
            this.props.onTabChange(tabName);
        }
        if (this.props.onClose) {
            this.props.onClose();
        }
    }
}
