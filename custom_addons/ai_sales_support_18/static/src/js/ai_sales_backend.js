/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";

// AI Sales Dashboard Component
class AISalesDashboard extends Component {
    static template = "ai_sales_support_18.dashboard";
    
    setup() {
        this.state = {
            stats: {
                total_inquiries: 0,
                completed_inquiries: 0,
                pending_inquiries: 0,
                success_rate: 0,
                avg_processing_time: 0
            },
            recent_inquiries: [],
            loading: true
        };
        
        this.loadDashboardData();
    }
    
    async loadDashboardData() {
        try {
            // Load dashboard statistics
            const stats = await this.env.services.rpc("/ai_sales/dashboard_stats");
            const recent = await this.env.services.rpc("/ai_sales/recent_inquiries", { limit: 5 });
            
            this.state.stats = stats;
            this.state.recent_inquiries = recent;
            this.state.loading = false;
            
            this.render();
        } catch (error) {
            console.error("Error loading dashboard data:", error);
            this.state.loading = false;
            this.render();
        }
    }
    
    onRefresh() {
        this.state.loading = true;
        this.render();
        this.loadDashboardData();
    }
}

// AI Sales Inquiry Form Widget
class AISalesInquiryFormWidget extends Component {
    static template = "ai_sales_support_18.inquiry_form_widget";
    
    setup() {
        this.inquiry = this.props.record.data;
    }
    
    get statusBadgeClass() {
        const state = this.inquiry.state;
        const classes = {
            'draft': 'badge-info',
            'processing': 'badge-warning',
            'inventory_check': 'badge-primary',
            'supplier_contact': 'badge-success',
            'quotation_ready': 'badge-info',
            'completed': 'badge-success',
            'failed': 'badge-danger'
        };
        return classes[state] || 'badge-secondary';
    }
    
    get processingProgress() {
        const state = this.inquiry.state;
        const progress = {
            'draft': 0,
            'processing': 20,
            'inventory_check': 40,
            'supplier_contact': 60,
            'quotation_ready': 80,
            'completed': 100,
            'failed': 0
        };
        return progress[state] || 0;
    }
    
    async onReprocess() {
        try {
            await this.env.services.rpc("/ai_sales/reprocess_inquiry", {
                inquiry_id: this.inquiry.id
            });
            
            this.env.services.notification.add("Inquiry reprocessing started", {
                type: "success"
            });
            
            // Reload the form
            await this.props.record.load();
            this.render();
        } catch (error) {
            console.error("Error reprocessing inquiry:", error);
            this.env.services.notification.add("Error reprocessing inquiry", {
                type: "danger"
            });
        }
    }
    
    async onCreateQuotation() {
        if (!this.inquiry.customer_id) {
            this.env.services.notification.add("Please select a customer first", {
                type: "warning"
            });
            return;
        }
        
        try {
            const result = await this.env.services.rpc("/ai_sales/create_quotation", {
                inquiry_id: this.inquiry.id
            });
            
            if (result.success) {
                this.env.services.notification.add("Quotation created successfully", {
                    type: "success"
                });
                
                // Open the quotation
                this.env.services.action.doAction({
                    type: 'ir.actions.act_window',
                    res_model: 'sale.order',
                    res_id: result.quotation_id,
                    views: [[false, 'form']],
                    target: 'current'
                });
            } else {
                throw new Error(result.error || "Unknown error");
            }
        } catch (error) {
            console.error("Error creating quotation:", error);
            this.env.services.notification.add("Error creating quotation: " + error.message, {
                type: "danger"
            });
        }
    }
}

// Supplier Contact Performance Widget
class SupplierPerformanceWidget extends Component {
    static template = "ai_sales_support_18.supplier_performance_widget";
    
    setup() {
        this.supplier = this.props.record.data;
    }
    
    get performanceClass() {
        const rate = this.supplier.success_rate;
        if (rate >= 90) return 'text-success';
        if (rate >= 70) return 'text-info';
        if (rate >= 50) return 'text-warning';
        return 'text-danger';
    }
    
    get responseTimeClass() {
        const time = this.supplier.response_time_avg;
        if (time <= 1) return 'text-success';
        if (time <= 4) return 'text-info';
        if (time <= 8) return 'text-warning';
        return 'text-danger';
    }
    
    async onTestConnection() {
        try {
            const result = await this.env.services.rpc("/ai_sales/test_supplier_connection", {
                supplier_id: this.supplier.id
            });
            
            if (result.success) {
                this.env.services.notification.add("Test message sent successfully", {
                    type: "success"
                });
            } else {
                throw new Error(result.error || "Connection test failed");
            }
        } catch (error) {
            console.error("Error testing supplier connection:", error);
            this.env.services.notification.add("Connection test failed: " + error.message, {
                type: "danger"
            });
        }
    }
}

// Communication Timeline Widget
class CommunicationTimelineWidget extends Component {
    static template = "ai_sales_support_18.communication_timeline_widget";
    
    setup() {
        this.communications = this.props.record.data.communication_log_ids || [];
    }
    
    get sortedCommunications() {
        return [...this.communications].sort((a, b) => 
            new Date(b.create_date) - new Date(a.create_date)
        );
    }
    
    getMessageTypeIcon(type) {
        return type === 'outgoing' ? 'fa-arrow-right text-primary' : 'fa-arrow-left text-success';
    }
    
    getStatusBadge(status) {
        const badges = {
            'sent': 'badge-info',
            'delivered': 'badge-primary',
            'read': 'badge-success',
            'replied': 'badge-success',
            'failed': 'badge-danger'
        };
        return badges[status] || 'badge-secondary';
    }
    
    formatDate(dateString) {
        return new Date(dateString).toLocaleString();
    }
}

// Register components
registry.category("fields").add("ai_sales_dashboard", AISalesDashboard);
registry.category("fields").add("ai_sales_inquiry_form_widget", AISalesInquiryFormWidget);
registry.category("fields").add("supplier_performance_widget", SupplierPerformanceWidget);
registry.category("fields").add("communication_timeline_widget", CommunicationTimelineWidget);

export {
    AISalesDashboard,
    AISalesInquiryFormWidget,
    SupplierPerformanceWidget,
    CommunicationTimelineWidget
};