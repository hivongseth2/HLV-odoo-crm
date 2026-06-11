/** @odoo-module **/

import { rpc } from "@web/core/network/rpc";

export const BarcodeApiService = {
    async callApi(endpoint, params = {}) {
        try {
            const response = await rpc(endpoint, params);
            if (response && response.error) {
                throw new Error(response.error);
            }
            return response;
        } catch (error) {
            console.error(`API Error [${endpoint}]:`, error);
            throw error;
        }
    },

    async getSettings() {
        return this.callApi('/api/barcode/get_settings');
    },

    async scanReceive(barcode) {
        return this.callApi('/api/barcode/receive/scan', { barcode });
    },

    async getAvailableToReceive(query) {
        return this.callApi('/api/barcode/get_available_to_receive', { search: query });
    },

    // ===== Deliver Tab APIs =====
    async scanPickOrder(barcode) {
        return this.callApi('/api/barcode/scan_pick', { barcode });
    },

    async getMultipleOutDetails(pickingIds) {
        return this.callApi('/api/barcode/get_multiple_outs', { picking_ids: pickingIds });
    },

    async scanPackageOrProduct(pickingId, barcode) {
        return this.callApi('/api/barcode/scan_package', { picking_id: pickingId, barcode });
    },

    async completeOut(pickingIds, additionalData = {}) {
        return this.callApi('/api/barcode/complete_out', { picking_ids: pickingIds, ...additionalData });
    },

    // Sẽ tiếp tục migrate dần các phương thức từ barcode_scanner.js cũ sang đây
};
