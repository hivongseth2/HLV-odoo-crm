odoo.define('stock_picking_barcode_next_group.barcode_override', function (require) {
    'use strict';

    const PickingClientAction = require('stock_barcode.PickingClientAction');
    const rpc = require('web.rpc');
    const core = require('web.core');

    const _superValidate = PickingClientAction.prototype.onValidate;

    PickingClientAction.include({
        async onValidate() {
            await _superValidate.apply(this, arguments);

            if (this.picking && this.picking.state === 'done' && this.picking.group_id) {
                const currentId = this.picking.id;
                const groupId = this.picking.group_id[0];

                try {
                    const res = await rpc.query({
                        model: 'stock.picking',
                        method: 'get_next_picking_by_group',
                        args: [currentId],
                        context: { group_id: groupId }
                    });

                    if (res.next_picking_id) {
                        console.log("🔁 Đang mở phiếu tiếp theo:", res.next_picking_id);
                        this.do_action('stock_barcode.stock_barcode_picking_client_action', {
                            additional_context: {
                                active_id: res.next_picking_id,
                                active_ids: [res.next_picking_id],
                                active_model: "stock.picking",
                            },
                        });
                    }
                } catch (err) {
                    console.warn("❌ Không tìm được phiếu kế tiếp:", err);
                }
            }
        }
    });
});
