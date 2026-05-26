/** @odoo-module **/

import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

export class PickingScanner extends Component {
    static template = "hlv_mobile_barcode.PickingScanner";
    static props = {
        pickingId: Number,
        onBack: Function,
        onSelectPicking: Function,
        onStateLoaded: { type: Function, optional: true },
        lastScannedProduct: { type: Number, optional: true },
        scannedLocationName: { type: String, optional: true },
        refreshTick: { type: Number, optional: true },
    };

    setup() {
        this.notification = useService("notification");
        this.actionService = useService("action");
        this.isProcessingQty = false;
        
        this.state = useState({
            picking: null,
            loading: true,
            editingLineId: null,
        });

        onWillStart(async () => {
            await this.loadPicking();
        });

        onWillUpdateProps(async (nextProps) => {
            if (nextProps.lastScannedProduct !== this.props.lastScannedProduct 
                || nextProps.scannedLocationName !== this.props.scannedLocationName
                || nextProps.refreshTick !== this.props.refreshTick) {
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
                if (this.props.onStateLoaded) {
                    this.props.onStateLoaded(data.state);
                }
                
                if (['draft', 'confirmed', 'assigned'].includes(data.state)) {
                    const storageKey = 'hlv_opened_pickings';
                    let openedPickings = [];
                    try {
                        openedPickings = JSON.parse(localStorage.getItem(storageKey) || '[]');
                    } catch (e) {
                        openedPickings = [];
                    }
                    
                    if (!openedPickings.includes(this.props.pickingId)) {
                        const clearRes = await rpc("/hlv_mobile_barcode/clear_quantities", { picking_id: this.props.pickingId });
                        if (!clearRes.error) {
                            openedPickings.push(this.props.pickingId);
                            if (openedPickings.length > 200) openedPickings = openedPickings.slice(openedPickings.length - 200);
                            localStorage.setItem(storageKey, JSON.stringify(openedPickings));
                            
                            // Re-fetch data after clearing
                            const newData = await rpc("/hlv_mobile_barcode/get_picking_data", { picking_id: this.props.pickingId });
                            if (!newData.error) {
                                if (this.props.onStateLoaded) {
                                    this.props.onStateLoaded(newData.state);
                                }
                                this.state.picking = newData;
                                this.state.loading = false;
                                return;
                            }
                        }
                    }
                }
                this.state.picking = data;
            }
        } catch (e) {
            this.notification.add("Failed to load picking", { type: "danger" });
        }
        this.state.loading = false;
    }

    async clearQuantities() {
        if (!confirm("Bạn có chắc muốn xoá toàn bộ số lượng đã quét để quét lại từ đầu không?")) {
            return;
        }
        try {
            const res = await rpc("/hlv_mobile_barcode/clear_quantities", {
                picking_id: this.props.pickingId,
            });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                this.notification.add("Đã làm mới số lượng", { type: "success" });
                await this.loadPicking();
            }
        } catch (e) {
            this.notification.add("Lỗi kết nối", { type: "danger" });
        }
    }

    toggleEditLine(moveId) {
        if (this.state.editingLineId === moveId) {
            this.state.editingLineId = null;
        } else {
            this.state.editingLineId = moveId;
        }
    }

    async adjustQty(line, change) {
        if (this.isProcessingQty) return;
        this.isProcessingQty = true;
        try {
            const res = await rpc("/hlv_mobile_barcode/update_move_line_qty", {
                move_id: line.move_id,
                qty_change: change
            });
            if (res.error) {
                this.playSound('error');
                this.notification.add(res.error, { type: "danger" });
            } else {
                line.qty_done = res.new_qty;
            }
        } catch (e) {
            this.playSound('error');
            this.notification.add("Lỗi kết nối", { type: "danger" });
        } finally {
            this.isProcessingQty = false;
        }
    }

    async saveQty(line, ev) {
        const newVal = parseFloat(ev.target.value);
        if (isNaN(newVal)) return;
        if (this.isProcessingQty) return;
        this.isProcessingQty = true;
        try {
            const res = await rpc("/hlv_mobile_barcode/update_move_line_qty", {
                move_id: line.move_id,
                new_qty: newVal
            });
            if (res.error) {
                this.playSound('error');
                this.notification.add(res.error, { type: "danger" });
                ev.target.value = line.qty_done;
            } else {
                line.qty_done = res.new_qty;
            }
        } catch (e) {
            this.playSound('error');
            this.notification.add("Lỗi kết nối", { type: "danger" });
            ev.target.value = line.qty_done;
        } finally {
            this.isProcessingQty = false;
        }
    }

    async deleteLine(line) {
        if (!confirm(`Bạn có chắc muốn xóa sản phẩm ${line.product_name}?`)) return;
        try {
            const res = await rpc("/hlv_mobile_barcode/delete_move", {
                move_id: line.move_id
            });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                this.notification.add("Đã xóa", { type: "success" });
                await this.loadPicking();
            }
        } catch (e) {
            this.notification.add("Lỗi kết nối", { type: "danger" });
        }
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
                await this.loadPicking();
            }
        } catch (e) {
            this.notification.add("Server error", { type: "danger" });
        }
    }

    playSound(type) {
        try {
            const audioPath = type === 'success' 
                ? '/custom_barcode_scan_redirect/static/src/sound/success.mp3' 
                : '/custom_barcode_scan_redirect/static/src/sound/error.mp3';
            const audio = new Audio(audioPath);
            audio.play().catch(e => console.error("Audio error:", e));
        } catch (e) {}
    }
}
