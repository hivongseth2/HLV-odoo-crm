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
        onBatchMove: { type: Function, optional: true },
    };

    setup() {
        this.action = useService("action");
        this.state = useState({
            title: "",
            location_barcode: "",
            location_name: "",
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
            this.state.location_barcode = data.location_barcode || "";
            this.state.location_name = data.location_name || "";
            this.state.results = data.results;
            this.state.reservations = data.reservations || [];
        } catch (e) {
            console.error(e);
        }
        this.state.loading = false;
    }

    openLocation(quantId) {
        if (!quantId) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'stock.quant',
            res_id: quantId,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    openPicking(pickingId) {
        if (!pickingId) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'stock.picking',
            res_id: pickingId,
            views: [[false, 'form']],
            target: 'current',
        });
    }
}
