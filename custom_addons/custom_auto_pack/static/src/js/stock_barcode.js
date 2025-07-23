odoo.define('custom_auto_pack.stock_barcode', function (require) {
    "use strict";

    var core = require('web.core');
    var StockBarcodeHandler = require('stock_barcode.PickingClientAction').PickingClientAction;
    var QWeb = core.qweb;

    StockBarcodeHandler.include({
        onBarcodeScanned: function(barcode) {
            var self = this;
            return this._rpc({
                model: 'stock.picking',
                method: 'action_done',
                args: [this.picking.id],
            }).then(function(result) {
                if (result && result.res_id) {
                    self.do_action(result);
                } else {
                    self._super.apply(self, arguments);
                }
            });
        },
    });
});