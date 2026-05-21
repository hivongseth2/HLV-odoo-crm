/** @odoo-module **/

import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

export class PickingScanner extends Component {
    static template = "hlv_mobile_barcode.PickingScanner";
    static props = {
        pickingId: Number,
        onBack: Function,
        lastScannedProduct: { type: Number, optional: true },
    };

    setup() {
        this.notification = useService("notification");
        this.actionService = useService("action");
        
        this.state = useState({
            picking: null,
            loading: true,
        });

        onWillStart(async () => {
            await this.loadPicking();
        });

        onWillUpdateProps(async (nextProps) => {
            if (nextProps.lastScannedProduct !== this.props.lastScannedProduct) {
                await this.loadPicking();
            }
        });
    }

    async loadPicking() {
        this.state.loading = true;
        try {
            const data = await rpc("/hlv_mobile_barcode/get_picking_data", { picking_id: this.props.pickingId });
            if (data.error) {
                this.notification.add(data.error, { type: "danger" });
            } else {
                this.state.picking = data;
            }
        } catch (e) {
            this.notification.add("Failed to load picking", { type: "danger" });
        }
        this.state.loading = false;
    }

    async doPack() {
        try {
            const res = await rpc("/hlv_mobile_barcode/put_in_pack", { picking_id: this.props.pickingId });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else if (res.success) {
                this.notification.add("Packed successfully", { type: "success" });
                if (res.print_after_pack && res.package_id) {
                    if (confirm("Do you want to print the label for this package?")) {
                        this.actionService.doAction({
                            type: 'ir.actions.report',
                            report_type: 'qweb-pdf',
                            report_name: 'stock.report_package_barcode',
                            report_file: 'stock.report_package_barcode',
                            context: { active_ids: [res.package_id] },
                        });
                    }
                }
                await this.loadPicking();
            }
        } catch (e) {
            this.notification.add("Server error", { type: "danger" });
        }
    }

    async doValidate() {
        try {
            const res = await rpc("/hlv_mobile_barcode/validate_picking", { picking_id: this.props.pickingId });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else if (res.success) {
                this.notification.add("Validated successfully", { type: "success" });
                this.props.onBack();
            }
        } catch (e) {
            this.notification.add("Server error", { type: "danger" });
        }
    }
}
