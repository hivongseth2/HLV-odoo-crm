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
            packagesExpanded: true,
            editingPackage: null,
            packageEditItems: [],
            packageAvailableItems: [],
            packageOtherPackages: [],
            addItemMoveLineId: "",
            addItemQty: 1,
            transferTargets: {},
            transferQtys: {},
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
                const storageKey = 'hlv_opened_pickings';
                try {
                    let opened = JSON.parse(localStorage.getItem(storageKey) || '[]');
                    opened = opened.filter(id => id !== this.props.pickingId);
                    localStorage.setItem(storageKey, JSON.stringify(opened));
                } catch (e) {}
                
                this.notification.add("Đã làm mới số lượng", { type: "success" });
                window.location.reload();
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
                move_line_id: line.id,
                qty_change: change
            });
            if (res.error) {
                this.playSound('error');
                this.notification.add(res.error, { type: "danger" });
            } else {
                line.qty_done = res.new_qty;
                if (!line.id) {
                    await this.loadPicking();
                }
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
                move_line_id: line.id,
                new_qty: newVal
            });
            if (res.error) {
                this.playSound('error');
                this.notification.add(res.error, { type: "danger" });
                ev.target.value = line.qty_done;
            } else {
                line.qty_done = res.new_qty;
                if (!line.id) {
                    await this.loadPicking();
                }
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
                move_id: line.move_id,
                move_line_id: line.id
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

    async unpackLine(line) {
        if (!confirm(`Bạn có chắc muốn gỡ dòng sản phẩm này ra khỏi kiện hàng ${line.package_name || ''}?`)) return;
        try {
            const res = await rpc("/hlv_mobile_barcode/unpack_move_line", {
                move_line_id: line.id
            });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                this.notification.add("Đã gỡ sản phẩm ra khỏi kiện thành công!", { type: "success" });
                this.playSound('success');
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
                const msg = res.package_name 
                    ? `Đóng gói thành công vào kiện ${res.package_name}!` 
                    : "Đóng gói thành công!";
                this.notification.add(msg, { type: "success" });
                this.playSound('success');
                if (res.print_after_pack && res.package_id) {
                    if (confirm(`Bạn có muốn in nhãn cho kiện hàng ${res.package_name || ''} không?`)) {
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
            this.notification.add("Lỗi kết nối", { type: "danger" });
        }
    }

    async doValidate() {
        try {
            const res = await rpc("/hlv_mobile_barcode/validate_picking", { picking_id: this.props.pickingId });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else if (res.success) {
                this.notification.add("Xác nhận phiếu thành công!", { type: "success" });
                this.playSound('success');
                await this.loadPicking();
            }
        } catch (e) {
            this.notification.add("Lỗi kết nối", { type: "danger" });
        }
    }

    togglePackages() {
        this.state.packagesExpanded = !this.state.packagesExpanded;
    }

    async openPackageEdit(pkg) {
        this.state.loading = true;
        try {
            const data = await rpc("/hlv_mobile_barcode/get_package_details", {
                picking_id: this.props.pickingId,
                package_id: pkg.id
            });
            if (data.error) {
                this.notification.add(data.error, { type: "danger" });
            } else {
                this.state.editingPackage = {
                    id: data.package_id,
                    name: data.package_name
                };
                this.state.packageEditItems = data.items.map(item => ({
                    ...item,
                    isChanged: false,
                    originalQty: item.qty_done
                }));
                this.state.packageAvailableItems = data.all_items;
                this.state.packageOtherPackages = data.other_packages;
                
                this.state.addItemMoveLineId = data.all_items.length > 0 ? String(data.all_items[0].move_line_id) : "";
                this.state.addItemQty = 1;

                this.state.transferTargets = {};
                this.state.transferQtys = {};
                for (const item of data.items) {
                    this.state.transferTargets[item.move_line_id] = data.other_packages.length > 0 ? String(data.other_packages[0].package_id) : "";
                    this.state.transferQtys[item.move_line_id] = 1;
                }
            }
        } catch (e) {
            this.notification.add("Không thể tải chi tiết kiện hàng", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    closePackageEdit() {
        this.state.editingPackage = null;
        this.state.packageEditItems = [];
        this.state.packageAvailableItems = [];
        this.state.packageOtherPackages = [];
        this.loadPicking();
    }

    pkgAdjustQty(item, delta) {
        const target = this.state.packageEditItems.find(i => i.move_line_id === item.move_line_id);
        if (target) {
            const newQty = target.qty_done + delta;
            if (newQty < 0) return;
            target.qty_done = newQty;
            target.isChanged = true;
        }
    }

    async pkgRemoveItem(item) {
        if (!confirm(`Bạn có chắc muốn bỏ sản phẩm ${item.product_name} ra khỏi kiện hàng này?`)) return;
        this.state.loading = true;
        try {
            const res = await rpc("/hlv_mobile_barcode/remove_package_item", {
                picking_id: this.props.pickingId,
                package_id: this.state.editingPackage.id,
                move_line_id: item.move_line_id
            });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                this.notification.add(res.message || "Đã bỏ sản phẩm khỏi kiện", { type: "success" });
                this.playSound('success');
                await this.openPackageEdit(this.state.editingPackage);
            }
        } catch (e) {
            this.notification.add("Lỗi kết nối", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async pkgAddItem() {
        const mlId = parseInt(this.state.addItemMoveLineId);
        const qty = parseFloat(this.state.addItemQty);
        if (!mlId || isNaN(qty) || qty <= 0) {
            this.notification.add("Sản phẩm hoặc số lượng không hợp lệ!", { type: "warning" });
            return;
        }
        
        this.state.loading = true;
        try {
            const res = await rpc("/hlv_mobile_barcode/add_item_to_package", {
                picking_id: this.props.pickingId,
                package_id: this.state.editingPackage.id,
                move_line_id: mlId,
                qty: qty
            });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                this.notification.add(res.message || "Đã thêm sản phẩm vào kiện", { type: "success" });
                this.playSound('success');
                await this.openPackageEdit(this.state.editingPackage);
            }
        } catch (e) {
            this.notification.add("Lỗi kết nối", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async pkgTransferItem(item) {
        const toPkgId = parseInt(this.state.transferTargets[item.move_line_id]);
        const qty = parseFloat(this.state.transferQtys[item.move_line_id]);
        
        if (!toPkgId || isNaN(qty) || qty <= 0 || qty > item.qty_done) {
            this.notification.add("Số lượng chuyển hoặc kiện đích không hợp lệ!", { type: "warning" });
            return;
        }
        
        this.state.loading = true;
        try {
            const res = await rpc("/hlv_mobile_barcode/transfer_item_between_packages", {
                picking_id: this.props.pickingId,
                from_package_id: this.state.editingPackage.id,
                to_package_id: toPkgId,
                move_line_id: item.move_line_id,
                qty: qty
            });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                this.notification.add(res.message || "Đã chuyển sản phẩm", { type: "success" });
                this.playSound('success');
                await this.openPackageEdit(this.state.editingPackage);
            }
        } catch (e) {
            this.notification.add("Lỗi kết nối", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async savePackageChanges() {
        const changedItems = this.state.packageEditItems.filter(i => i.isChanged);
        if (changedItems.length === 0) {
            this.closePackageEdit();
            return;
        }
        
        this.state.loading = true;
        try {
            let hasError = false;
            for (const item of changedItems) {
                const res = await rpc("/hlv_mobile_barcode/update_package_item_qty", {
                    picking_id: this.props.pickingId,
                    package_id: this.state.editingPackage.id,
                    move_line_id: item.move_line_id,
                    new_qty: item.qty_done
                });
                if (res.error) {
                    this.notification.add(`${item.product_name}: ${res.error}`, { type: "danger" });
                    hasError = true;
                    break;
                }
            }
            if (!hasError) {
                this.notification.add("Lưu thay đổi kiện hàng thành công!", { type: "success" });
                this.playSound('success');
                this.closePackageEdit();
            }
        } catch (e) {
            this.notification.add("Lỗi kết nối khi lưu thay đổi", { type: "danger" });
        } finally {
            this.state.loading = false;
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
