/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

export class InventoryLookup extends Component {
    static template = "hlv_mobile_barcode.InventoryLookup";
    static props = {
        lookupType: String,
        recordId: Number,
        onBack: Function,
        onMove: { type: Function, optional: true },
        onBatchMove: { type: Function, optional: true },
        onPackageMove: { type: Function, optional: true },
        onProductSelect: { type: Function, optional: true },
    };

    setup() {
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            title: "",
            location_id: false,
            location_barcode: "",
            location_name: "",
            can_unpack_package: false,
            can_move_package: false,
            results: [],
            reservations: [],
            loading: true,
            actionLoading: false,
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData() {
        this.state.loading = true;
        try {
            const data = await rpc("/hlv_mobile_barcode/get_inventory_lookup", { 
                lookup_type: this.props.lookupType,
                record_id: this.props.recordId
            });
            if (data.error) {
                this.notification.add(data.error, { type: "danger" });
                this.state.can_unpack_package = false;
                this.state.can_move_package = false;
                this.state.results = [];
                this.state.reservations = [];
                this.state.loading = false;
                return;
            }
            this.state.title = data.title;
            this.state.location_id = data.location_id || false;
            this.state.location_barcode = data.location_barcode || "";
            this.state.location_name = data.location_name || "";
            this.state.can_unpack_package = !!data.can_unpack_package;
            this.state.can_move_package = !!data.can_move_package;
            this.state.results = data.results || [];
            this.state.reservations = data.reservations || [];
        } catch (e) {
            console.error(e);
        }
        this.state.loading = false;
    }

    openLocation(quantId) {
        if (!quantId) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'stock.quant',
            res_id: quantId,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    async unpackPackage() {
        if (this.state.actionLoading || this.props.lookupType !== 'package') return;
        if (!confirm(`Bạn có chắc muốn gỡ kiện "${this.state.title}" thành hàng lẻ không?`)) {
            return;
        }
        this.state.actionLoading = true;
        try {
            const res = await rpc("/hlv_mobile_barcode/unpack_inventory_package", {
                package_id: this.props.recordId,
            });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                this.notification.add(res.message || "Đã gỡ kiện thành hàng lẻ", { type: "success" });
                await this.loadData();
            }
        } catch (e) {
            this.notification.add("Lỗi kết nối máy chủ", { type: "danger" });
        } finally {
            this.state.actionLoading = false;
        }
    }

    movePackage() {
        if (!this.props.onPackageMove || this.props.lookupType !== 'package') return;
        if (!this.state.location_id) {
            this.notification.add("Không xác định được vị trí hiện tại của kiện", { type: "warning" });
            return;
        }
        this.props.onPackageMove(
            this.props.recordId,
            this.state.title,
            this.state.location_id,
            this.state.location_barcode,
            this.state.location_name
        );
    }

    openPicking(pickingId) {
        if (!pickingId) return;
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'stock.picking',
            res_id: pickingId,
            views: [[false, 'form']],
            target: 'current',
        });
    }
}
