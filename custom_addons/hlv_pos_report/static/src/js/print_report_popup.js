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
        order: Object,
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
        });
        this.loadData();
    }

    async loadData() {
        try {
            // Load danh sách reports
            await this.pos.loadHlvReports();
            this.state.reports = this.pos.hlvReports || [];

            // Kiểm tra xem order có picking không
            if (this.props.order && this.props.order.backendId) {
                const pickings = await this.pos.getPickingsForOrder(this.props.order.backendId);
                this.state.hasPickings = pickings.length > 0;
            }

            // Set default selection
            if (this.state.reports.length > 0) {
                this.state.selectedReportId = this.state.reports[0].id;
            }
        } catch (error) {
            console.error('[HLV POS Report] Error loading data:', error);
            this.notification.add("Lỗi tải danh sách biên bản", { type: "danger" });
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

        if (!this.props.order || !this.props.order.backendId) {
            this.notification.add("Không tìm thấy đơn hàng", { type: "danger" });
            return;
        }

        this.state.printing = true;

        try {
            const result = await this.pos.printHlvReport(
                this.props.order.backendId,
                this.state.selectedReportId
            );

            if (result.error) {
                this.notification.add(result.error, { type: "danger" });
            } else if (result.url) {
                // Mở PDF trong tab mới
                window.open(result.url, '_blank');
                this.notification.add("Đã mở biên bản để in", { type: "success" });
                this.props.close();
            }
        } catch (error) {
            console.error('[HLV POS Report] Error printing:', error);
            this.notification.add("Lỗi khi in biên bản: " + error.message, { type: "danger" });
        } finally {
            this.state.printing = false;
        }
    }

    onClose() {
        this.props.close();
    }
}
