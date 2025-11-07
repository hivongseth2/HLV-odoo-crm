/** @odoo-module **/
console.log('[HLV] barcode_inline_qty.js LOADED');

import { registry } from '@web/core/registry';

registry.category('barcode_handlers').add('hlv_test_inline_load', {
    sequence: 10000,
    handler(env, barcode) {
        console.log('[HLV] barcode handler fired with:', barcode);
        return false; // không chặn handler khác
    },
});
