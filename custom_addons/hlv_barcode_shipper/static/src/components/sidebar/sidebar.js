/** @odoo-module **/

import { Component, xml } from "@odoo/owl";

export class Sidebar extends Component {
    static template = xml`<div>
            <!-- Sidebar Overlay -->
            <div class="sidebar-overlay" 
                 t-att-class="{ 'show': props.isOpen }" 
                 t-on-click="props.onClose"></div>

            <!-- Sidebar Navigation -->
            <div class="sidebar-nav" t-att-class="{ 'open': props.isOpen }">
                <div class="sidebar-header">
                    <div class="header-title">
                        <i class="fa fa-shipping-fast"></i> Menu
                    </div>
                    <button class="btn btn-text" style="color: #6c757d; font-size: 1.2rem; padding: 0;" t-on-click="props.onClose">
                        <i class="fa fa-times"></i>
                    </button>
                </div>
                
                <div class="sidebar-body">
                    <div class="tab-nav sidebar-tabs">
                        <button class="tab-btn" t-att-class="{ 'active': props.activeTab === 'receive' }" t-on-click="() => this.onTabClick('receive')">
                            <i class="fa fa-inbox"></i> Nhận hàng
                        </button>
                        <button class="tab-btn" t-att-class="{ 'active': props.activeTab === 'deliver' }" t-on-click="() => this.onTabClick('deliver')">
                            <i class="fa fa-truck"></i> Giao hàng
                        </button>
                        <button class="tab-btn" t-att-class="{ 'active': props.activeTab === 'return' }" t-on-click="() => this.onTabClick('return')">
                            <i class="fa fa-undo-alt"></i> Trả hàng
                        </button>
                        <button class="tab-btn" t-att-class="{ 'active': props.activeTab === 'delivered' }" t-on-click="() => this.onTabClick('delivered')">
                            <i class="fa fa-clipboard-check"></i> Đã giao
                        </button>
                    </div>
                </div>
                
                <div class="sidebar-footer" style="margin-top: auto; padding: 15px; border-top: 1px solid #f0f0f0;">
                    <button class="btn btn-text" style="width: 100%; text-align: left; padding: 10px 5px; color: #6c757d; font-weight: 600; font-size: 0.95rem; justify-content: flex-start; gap: 8px;">
                        <i class="fa fa-user-circle"></i> Tài xế khác
                    </button>
                </div>
            </div>
        </div>`;
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
