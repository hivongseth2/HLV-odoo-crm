/** @odoo-module **/

import Dialog from "@web/legacy/js/core/dialog";
import { _t } from "@web/core/l10n/translation";
import { session } from "@web/session";
import { FormController } from '@web/views/form/form_controller';
import { WarningDialog } from "@web/core/errors/error_dialogs";
import { ORM } from "@web/core/orm_service";
import { Record } from "@web/model/relational_model/record";
import { patch } from "@web/core/utils/patch";


$(function() {
    var _passive = false;
    try {
        const options = {
            get passive () {
                _passive = true;
                return false;
            }
        };
        window.addEventListener("test", null, options);
        window.removeEventListener("test", null, options);
    } catch (e) {}
    const Fn = EventTarget.prototype.addEventListener;
    EventTarget.prototype.addEventListener = function(...args) {
        if (["scroll", "touchstart", "touchmove"].includes(args[0]) && (typeof args[2] !== "object" || args[2].passive === undefined)) {
            args[2] = {
                ...(typeof args[2] === "object" ? args[2] : {}),
                passive: _passive
            };
        }
        Fn.call(this, ...args);
    }
});

const MIDDLEWARE_ALERT_TITLE = "Middleware Alert";

async function middleware_alert(self, msg, buttons) {
    var _buttons = buttons || [{
        text: _t("GOT IT"),
        close: true,
    }];
    await new Dialog(self, {
        title: _t(MIDDLEWARE_ALERT_TITLE),
        size: "medium",
        buttons: _buttons,
        $content: msg
    }).open();
    return false;
}

patch(FormController.prototype, {
    async onSaveError(error, { discard }) {
        const proceed = await new Promise((resolve) => {
            if (String(error.data.message).toLowerCase().includes("inventory audit")) {
                var _buttons = [{
                    text: _t("STAY HERE"),
                    close: true,
                    click: () => {
                        return false;
                    }
                }, {
                    text: _t("DISCARD CHANGES"),
                    classes: "btn-primary",
                    close: true,
                    click: () => {
                        discard();
                        return true;
                    }
                }];
                resolve(middleware_alert(this, $("<div>").append(_t(error.data.message)), _buttons));
            } else {
                resolve(super.onSaveError(error, { discard }));
            }
        });
        return proceed;
    }
});

patch(WarningDialog.prototype, {
    setup() {
        super.setup();
        if (this.title && this.title.toString().toLowerCase().includes(_t("access error")) && this.message && this.message.toString().toLowerCase().includes(_t("inventory audit"))) {
            this.props.close();
            setTimeout(() => {
                var _popups = $(".modal-dialog");
                if (_popups.length) {
                    var _title = $(_popups[_popups.length - 1]).find(".modal-title")[0].innerText;
                    if (_title === _t(MIDDLEWARE_ALERT_TITLE)) {
                        $(_popups[_popups.length - 1]).find(".btn-close")[0].click();
                    }
                }
                middleware_alert(this, $("<div>").append(_t(this.message)));
            });
        }
    }
});

function verify_order_lines(_rpc, _user, _model, _order_id, _lines) {
    return new Promise(async (resolve) => {
        var _content = "";
        var _orm = new ORM(_rpc, _user);
        if (_order_id) {
            var _state = await _orm.call(_model, "read", [[_order_id], ["state"]]);
            if (_model === "purchase.order" && _state[0].state === "purchase") {
                _content = $("<div>");
                _content.append(_t("A confirmed purchase order cannot be modified! You can cancel this order and create a new one."));
            } else if (_model === "sale.order" && _state[0].state === "sale") {
                _content = $("<div>");
                _content.append(_t("A confirmed sales order cannot be modified! You can cancel this order and create a new one."));
            }
        }

        if (_content.length === 0 && _lines.length > 0) {
            var _tmp_names = [];
            for (var i = 0; i < _lines.length; i++) {
                if (_tmp_names.includes(_lines[i].name)) {
                    _content = $("<div>");
                    _content.append($("<b>", { text: _lines[i].name }));
                    _content.append(_t(" cannot be added twice!"));
                    break;
                } else {
                    _tmp_names.push(_lines[i].name);
                }
            }
        }

        if (_content.length === 0 && _lines.length > 0) {
            var _product_id = _lines[_lines.length - 1].id;
            var _product = await _orm.call("product.product", "read", [[_product_id], ["name", "barcode", "company_id"]]);
            if (_product.length > 0) {
                if (!_product[0].barcode) {
                    _content = $("<div>");
                    _content.append($("<b>", { text: _product[0].name }));
                    _content.append(_t(" has no valid barcode!"));
                } else {
                    if (_product[0].company_id === false || _product[0].company_id[0] !== session.user_companies.current_company) {
                        for (const [_key, _val] of Object.entries(session.user_companies.allowed_companies)) {
                            if (_val.id === session.user_companies.current_company) {
                                _content = $("<div>");
                                _content.append($("<b>", { text: _product[0].name }));
                                _content.append(_t(" is not linked with the company "));
                                _content.append($("<b>", { text: _val.name }));
                                _content.append(".");
                                break;
                            }
                        }
                    }
                }
            }
        }

        resolve(_content);
    });
}

patch(Record.prototype, {
    async _applyChanges(changes, serverChanges = {}) {
        var _content = "";
        if (changes.hasOwnProperty("order_line")) {
            if (changes.order_line._config.resModel === "purchase.order.line" || changes.order_line._config.resModel === "sale.order.line") {
                var _lines = [];
                var _order_lines = changes.order_line.records;
                for (var i = 0; i < _order_lines.length; i++) {
                    if (_order_lines[i].data.product_id[0]) {
                        var _obj = {};
                        _obj.id = _order_lines[i].data.product_id[0];
                        _obj.name = _order_lines[i].data.product_id[1];
                        _lines.push(_obj);
                    }
                }

                if (_lines.length > 0) {
                    var _rpc = changes.order_line.model.rpc;
                    var _user = changes.order_line.model.user;
                    var _model = changes.order_line.model.config.resModel || null;
                    var _order_id = changes.order_line.model.config.resId || null;
                    _content = await verify_order_lines(_rpc, _user, _model, _order_id, _lines);
                }
            }
        } else {
            if (changes.hasOwnProperty("move_line_ids")) {
                if (changes.move_line_ids._config.resModel === "stock.move.line") {
                    var _lines = changes.move_line_ids.records;
                    for (var i = 0; i < _lines.length; i++) {
                        if (_content.length === 0 && _lines[i].data.picking_code === "incoming" && _lines[i].data.tracking === "lot" && _lines[i].data.quantity && parseFloat(_lines[i].data.quantity) < 2) {
                            _content = $("<div>");
                            _content.append(_t("Lot-based product quantity must be more than 1."));
                        }
                    }
                }
            } else if (changes.hasOwnProperty("move_ids_without_package")) {
                if (changes.move_ids_without_package._config.resModel === "stock.move") {
                    var _recs = changes.move_ids_without_package.records;
                    for (var i = 0; i < _recs.length; i++) {
                        if (_content.length === 0 && _recs[i].data.picking_code === "incoming" && _recs[i].data.has_tracking === "lot") {
                            var _lines = _recs[i].data.move_line_ids.records;
                            for (var j = 0; j < _lines.length; j++) {
                                if (_content.length === 0 && _lines[j].data.quantity && parseFloat(_lines[j].data.quantity) < 2) {
                                    _content = $("<div>");
                                    _content.append(_t("Lot-based product quantity must be more than 1."));
                                }
                            }
                        }
                    }
                }
            }
        }
        if (_content.length > 0) {
            if ($(".modal-title").length < 2) {
                middleware_alert(this, _content)
            }
            return false;
        }

        return super._applyChanges(changes, serverChanges);
    },
    async _save({ reload = true, onError, nextId } = {}) {
        if (this && this._changes && Object.keys(this._changes).length > 0 && this.data && this.data.order_line && this.data.order_line.records) {
            var _lines = [];
            var _order_lines = this.data.order_line.records;
            for (var i = 0; i < _order_lines.length; i++) {
                if (_order_lines[i].data.product_id[0]) {
                    var _obj = {};
                    _obj.id = _order_lines[i].data.product_id[0];
                    _obj.name = _order_lines[i].data.product_id[1];
                    _lines.push(_obj);
                }
            }

            if (_lines.length > 0) {
                var _rpc = this.model.rpc;
                var _user = this.model.user;
                var _model = null;
                var _order_id = null;
                var _content = await verify_order_lines(_rpc, _user, _model, _order_id, _lines);
                if (_content.length > 0) {
                    return middleware_alert(this, _content)
                }
            }
        }

        return super._save({ reload: true, onError, nextId });
    }
});