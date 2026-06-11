/** @odoo-module **/

import { Component, xml, useState } from "@odoo/owl";

export class DeliveredTab extends Component {
    static template = xml`<div class="tab-content active">
            <div class="filter-bar p-3" style="background:#f8f9fa;">
                <div class="input-group-row">
                    <input type="date" class="form-control" t-model="state.dateFilter" />
                    <button class="btn btn-secondary" t-on-click="loadDeliveredList">
                        <i class="fa fa-filter"></i> Lọc
                    </button>
                </div>
            </div>
            <div class="mt-3 text-center text-muted">
                <p>Danh sách các phiếu Đã Giao. Đang cấu trúc...</p>
            </div>
        </div>`;

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
