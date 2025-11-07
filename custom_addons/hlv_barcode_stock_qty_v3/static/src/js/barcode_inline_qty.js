/** @odoo-module **/

import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';

function insertInlineForBarcode(barcode, text, tries = 0) {
    const qtyEl = document.querySelector(`.o_barcode_line[data-barcode="${barcode}"] .o_barcode_scanner_qty`);
    if (qtyEl) {
        let badge = qtyEl.parentElement.querySelector('.hlv-inline-stock');
        if (!badge) {
            badge = document.createElement('small');
            badge.className = 'hlv-inline-stock';
            badge.style.marginLeft = '8px';
            badge.style.fontSize = '12px';
            badge.style.color = '#0a7';
            qtyEl.parentElement.appendChild(badge);
        }
        badge.textContent = `| tồn: ${text}`;
        return true;
    }
    if (tries < 5) setTimeout(() => insertInlineForBarcode(barcode, text, tries + 1), 150);
    return false;
}

registry.category('barcode_handlers').add('hlv_show_stock_qty_inline', {
    sequence: 10000,
    async handler(env, barcode) {
        if (!location.pathname.includes('/odoo/barcode/')) return false;
        const orm = env.services.orm || useService('orm');
        try {
            const result = await orm.call('stock.quant', 'get_qty_by_barcode', [barcode], {});
            if (result && !result.error) insertInlineForBarcode(barcode, `${result.qty} ${result.uom}`);
        } catch (e) { console.debug('HLV inline err:', e); }
        return false;
    },
});
