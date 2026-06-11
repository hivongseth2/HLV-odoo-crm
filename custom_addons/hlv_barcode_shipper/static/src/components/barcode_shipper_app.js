/** @odoo-module **/

import { Component, xml, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { Sidebar } from "./sidebar/sidebar";
import { ReceiveTab } from "./receive_tab/receive_tab";
import { DeliverTab } from "./deliver_tab/deliver_tab";
import { ReturnTab } from "./return_tab/return_tab";
import { DeliveredTab } from "./delivered_tab/delivered_tab";

export class BarcodeShipperApp extends Component {
    static template = xml`<div class="hlv-barcode-shipper">
            <div class="shipper-container">
                
                <!-- Header -->
                <div class="shipper-header" style="padding: 15px;">
                    <div class="header-title" t-on-click="() => state.isSidebarOpen = true" style="cursor: pointer;">
                        <i class="fa fa-shipping-fast"></i> Shipper
                    </div>
                </div>

                <!-- Sidebar Component -->
                <Sidebar 
                    isOpen="state.isSidebarOpen"
                    activeTab="state.activeTab"
                    onClose="() => state.isSidebarOpen = false"
                    onTabChange="switchTab.bind(this)"
                />

                <!-- Tab Contents (sẽ được implement dần) -->
                <div class="tab-content-area">
                    <t t-if="state.activeTab === 'receive'">
                        <ReceiveTab />`;
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
