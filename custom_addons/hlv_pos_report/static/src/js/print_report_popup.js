/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";

export class PrintReportPopup extends Component {
    static template = "hlv_pos_report.PrintReportPopup";
    static components = { Dialog };
    static props = {
        close: Function,
        order: { type: Object, optional: true },
    };

    setup() {
        this.pos = usePos();
        this.notification = useService("notification");
        this.state = useState({
            reports: [],
            selectedReportId: null,
            loading: true,
            printing: false,
            hasPickings: false,
            pickingInfo: null,
            orderId: null,
        });
        this.loadData();
    }

    getOrderId() {
        // Thử nhiều cách để lấy order ID
        const order = this.props.order || this.pos.get_order();
        if (!order) return null;

        // Odoo 18 có thể sử dụng các tên khác nhau
        const possibleIds = [
            order.backendId,
            order.backend_id,
            order.id,
            order.server_id,
            order.pos_order_id,
        ];

        for (const id of possibleIds) {
            if (id && typeof id === 'number' && id > 0) {
                console.log('[HLV POS Report] Found order ID:', id);
                return id;
            }
        }

        console.warn('[HLV POS Report] Could not find order ID. Order:', order);
        return null;
    }

    async loadData() {
        try {
            // Load danh sách reports
            await this.pos.loadHlvReports();
            this.state.reports = this.pos.hlvReports || [];

            // Lấy order ID
            this.state.orderId = this.getOrderId();
            console.log('[HLV POS Report] Order ID for report:', this.state.orderId);

            // Kiểm tra xem order có picking không
            if (this.state.orderId) {
                const pickings = await this.pos.getPickingsForOrder(this.state.orderId);
                this.state.hasPickings = pickings && pickings.length > 0;
                console.log('[HLV POS Report] Has pickings:', this.state.hasPickings, pickings);
            }

            // Set default selection
            if (this.state.reports.length > 0) {
                this.state.selectedReportId = this.state.reports[0].id;
            }
        } catch (error) {
            console.error('[HLV POS Report] Error loading data:', error);
            this.notification.add("Lỗi tải danh sách biên bản: " + (error.message || error), { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    onReportChange(ev) {
        this.state.selectedReportId = parseInt(ev.target.value);
    }

    async onPrint() {
        if (!this.state.selectedReportId) {
            this.notification.add("Vui lòng chọn mẫu biên bản", { type: "warning" });
            return;
        }

        if (!this.state.orderId) {
            this.notification.add("Không tìm thấy ID đơn hàng. Vui lòng thử lại sau.", { type: "danger" });
            return;
        }

        this.state.printing = true;

        try {
            const result = await this.pos.printHlvReport(
                this.state.orderId,
                this.state.selectedReportId
            );

            console.log('[HLV POS Report] Print result:', result);

            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
            } else if (result.url) {
                // Mở PDF trong tab mới
                window.open(result.url, '_blank');
                this.notification.add(`Đã mở biên bản (${result.picking_name || 'Picking'})`, { type: "success" });
                this.props.close();
            }
        } catch (error) {
            console.error('[HLV POS Report] Error printing:', error);
            this.notification.add("Lỗi khi in biên bản: " + (error.message || error), { type: "danger" });
        } finally {
            this.state.printing = false;
        }
    }

    onClose() {
        this.props.close();
    }
}
