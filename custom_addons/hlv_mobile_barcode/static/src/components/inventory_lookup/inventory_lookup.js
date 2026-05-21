/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

export class InventoryLookup extends Component {
    static template = "hlv_mobile_barcode.InventoryLookup";
    static props = {
        lookupType: String,
        recordId: Number,
        onBack: Function,
        onMove: { type: Function, optional: true },
    };

    setup() {
        this.state = useState({
            title: "",
            results: [],
            reservations: [],
            loading: true,
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData() {
        this.state.loading = true;
        try {
            const data = await rpc("/hlv_mobile_barcode/get_inventory_lookup", { 
                lookup_type: this.props.lookupType,
                record_id: this.props.recordId
            });
            this.state.title = data.title;
            this.state.results = data.results;
            this.state.reservations = data.reservations || [];
        } catch (e) {
            console.error(e);
        }
        this.state.loading = false;
    }
}
