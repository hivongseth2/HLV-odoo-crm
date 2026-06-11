/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Sidebar } from "./sidebar/sidebar";
import { ReceiveTab } from "./receive_tab/receive_tab";
import { DeliverTab } from "./deliver_tab/deliver_tab";
import { ReturnTab } from "./return_tab/return_tab";
import { DeliveredTab } from "./delivered_tab/delivered_tab";

export class BarcodeShipperApp extends Component {
    static template = "hlv_barcode_shipper.BarcodeShipperApp";
    static components = { Sidebar, ReceiveTab, DeliverTab, ReturnTab, DeliveredTab };

    setup() {
        this.state = useState({
            activeTab: "receive",
            settings: {},
        });

        onWillStart(async () => {
            await this.loadSettings();
        });
    }

    async loadSettings() {
        // Dịch vụ tải settings từ API
        // Giả lập cho việc setup khung sườn
        this.state.settings = { skip_package_scan: false };
    }

    switchTab(tabName) {
        this.state.activeTab = tabName;
    }
}

// Đăng ký component vào public widget hoặc action registry
// Tùy theo cách gọi của standalone page
registry.category("actions").add("hlv_barcode_shipper.app", BarcodeShipperApp);
