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

    // Sẽ tiếp tục migrate dần các phương thức từ barcode_scanner.js cũ sang đây
};
