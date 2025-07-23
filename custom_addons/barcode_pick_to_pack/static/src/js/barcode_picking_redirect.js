// File: static/src/js/barcode_picking_redirect.js

odoo.define('barcode_pick_to_pack.barcode_picking_redirect', function (require) {
    'use strict';

    const BarcodePickingClientAction = require('stock_barcode.PickingClientAction');
    const viewRegistry = require('web.view_registry');

    const { patch } = require('web.utils');

    patch(BarcodePickingClientAction.prototype, 'barcode_pick_to_pack', {
        async _loadPicking(picking) {
            // Nếu phiếu đã done, thì tìm phiếu pack liên quan
            if (picking.state === 'done') {
                const packs = await this._rpc({
                    model: 'stock.picking',
                    method: 'search_read',
                    domain: [
                        ['origin', '=', picking.name],
                        ['state', 'not in', ['done', 'cancel']],
                        ['picking_type_id.code', '=', 'outgoing']
                    ],
                    fields: ['id', 'name']
                });

                if (packs.length > 0) {
                    const packId = packs[0].id;
                    // Load lại với phiếu pack mới
                    return this._super({ id: packId });
                } else {
                    this.do_warn('Không tìm thấy phiếu pack liên quan chưa done.');
                }
            }

            return this._super(...arguments);
        },
    });

    return BarcodePickingClientAction;
});
