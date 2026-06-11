/** @odoo-module **/

import { Component, useState } from "@odoo/owl";

export class DeliveredTab extends Component {
    static template = "hlv_barcode_shipper.DeliveredTab";

    setup() {
        this.state = useState({
            dateFilter: new Date().toISOString().slice(0, 10),
            pickings: [],
            isLoading: false
        });
    }

    loadDeliveredList() {
        // Fetch delivered items logic
    }
}
