/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";

// Patch PosStore để thêm method load reports
patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        this.hlvReports = [];
    },

    async loadHlvReports() {
        try {
            const result = await this.env.services.orm.call(
                'pos.order',
                'get_available_reports_for_picking',
                []
            );
            this.hlvReports = result || [];
            console.log('[HLV POS Report] Loaded reports:', this.hlvReports);
        } catch (error) {
            console.error('[HLV POS Report] Error loading reports:', error);
            this.hlvReports = [];
        }
    },

    async printHlvReport(orderId, reportId) {
        try {
            const result = await this.env.services.orm.call(
                'pos.order',
                'print_report_for_pos_order',
                [orderId, reportId]
            );
            return result;
        } catch (error) {
            console.error('[HLV POS Report] Error printing report:', error);
            return { error: error.message };
        }
    },

    async getPickingsForOrder(orderId) {
        try {
            const result = await this.env.services.orm.call(
                'pos.order',
                'get_picking_ids_for_pos_order',
                [orderId]
            );
            return result || [];
        } catch (error) {
            console.error('[HLV POS Report] Error getting pickings:', error);
            return [];
        }
    }
});
