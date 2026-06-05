/** @odoo-module **/

import { Component, useState, onWillStart, onWillUpdateProps, useEffect, onWillDestroy, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

export class PickingScanner extends Component {
    static template = "hlv_mobile_barcode.PickingScanner";
    static props = {
        pickingId: { type: [Number, Boolean, String], optional: true },
        onBack: Function,
        onSelectPicking: Function,
        onStateLoaded: { type: Function, optional: true },
        onPickingLoaded: { type: Function, optional: true },
        lastScannedProduct: { optional: true },
        scannedLocationName: { type: [String, Boolean], optional: true },
        refreshTick: { type: Number, optional: true },
        scanMode: { type: [String, Boolean], optional: true },
        onToggleScanMode: { type: Function, optional: true },
        isMultiLocationMode: { type: Boolean, optional: true },
        onDirectGoToMain: { type: Function, optional: true },
    };

    setup() {
        this.notification = useService("notification");
        this.actionService = useService("action");
        this.isProcessingQty = false;
        this._hasAutoCleared = false;
        this.isDestroyed = false;
        this.locationValRef = useRef("locationValRef");

        onWillDestroy(() => {
            this.isDestroyed = true;
        });
        
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
            if (nextProps.pickingId !== this.props.pickingId) {
                this._hasAutoCleared = false;
            }
            if (nextProps.lastScannedProduct !== this.props.lastScannedProduct 
                || nextProps.scannedLocationName !== this.props.scannedLocationName
                || nextProps.refreshTick !== this.props.refreshTick
                || nextProps.pickingId !== this.props.pickingId) {
                await this.loadPicking();
            }
        });

        useEffect(() => {
            if (!this.state.loading && this.props.lastScannedProduct) {
                // lastScannedProduct is actually the product_id from the backend (res.product_id)
                const productId = Number(this.props.lastScannedProduct);
                const element = document.querySelector(`[data-product-id="${productId}"] .item-card`);
                if (element) {
                    element.classList.remove('flash-highlight');
                    void element.offsetWidth; // Force CSS reflow to restart animation
                    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    element.classList.add('flash-highlight');
                    setTimeout(() => {
                        if (element) element.classList.remove('flash-highlight');
                    }, 1500);
                }
            }
        }, () => [this.props.lastScannedProduct, this.props.refreshTick, this.state.loading]);

        useEffect(() => {
            const el = this.locationValRef.el;
            if (el) {
                // Tắt transition và ẩn đi để tính toán (không cho user thấy quá trình nhỏ dần)
                const prevTransition = el.style.transition;
                el.style.transition = "none";
                el.style.opacity = "0";
                
                // Reset to default
                el.style.fontSize = "0.85rem";
                let currentFontSize = 0.85;
                
                // Shrink until it fits or reaches a minimum readable size
                while (el.scrollWidth > el.clientWidth && currentFontSize > 0.4) {
                    currentFontSize -= 0.05; // Decrease faster to reduce layout thrashing
                    el.style.fontSize = `${currentFontSize}rem`;
                }
                
                // Hiển thị lại ngay lập tức
                el.style.opacity = "1";
                // Phục hồi transition sau 1 frame nhỏ
                requestAnimationFrame(() => {
                    if (el) el.style.transition = prevTransition;
                });
            }
        }, () => [this.props.scannedLocationName]);
    }

    async loadPicking() {
        this.state.loading = true;
        try {
            let data = await rpc("/hlv_mobile_barcode/get_picking_data", { picking_id: this.props.pickingId });
            if (data.error) {
                this.notification.add(data.error, { type: "danger" });
                if (this.props.onDirectGoToMain) {
                    this.props.onDirectGoToMain();
                } else {
                    this.props.onBack();
                }
            } else {
                if (this.props.onStateLoaded) {
                    this.props.onStateLoaded(data.state);
                }
                if (this.props.onPickingLoaded) {
                    this.props.onPickingLoaded(data);
                }
                
                if (['draft', 'waiting', 'confirmed', 'assigned'].includes(data.state)) {
                    const storageKey = 'hlv_opened_pickings';
                    let openedPickings = [];
                    try {
                        openedPickings = JSON.parse(localStorage.getItem(storageKey) || '[]');
                    } catch (e) {}
                    
                    const pickingIdInt = parseInt(this.props.pickingId, 10);
                    
                    if (data.is_pick && !data.hlv_barcode_auto_cleared && !this.hasAutoClearedOnce) {
                        this.hasAutoClearedOnce = true;
                        // Gọi hàm Làm lại (chỉ tự động chạy 1 lần duy nhất cho mỗi phiếu)
                        try {
                            await this.clearQuantities(true);
                        } finally {
                            this.state.loading = false;
                        }
                        return;
                    }
                    
                    if (!openedPickings.includes(pickingIdInt)) {
                        openedPickings.push(pickingIdInt);
                        if (openedPickings.length > 200) openedPickings = openedPickings.slice(openedPickings.length - 200);
                        localStorage.setItem(storageKey, JSON.stringify(openedPickings));
                    }
                }
                this.state.picking = data;
            }
        } catch (e) {
            this.notification.add("Failed to load picking", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async clearQuantities(skipConfirm = false) {
        if (!skipConfirm && !confirm("Bạn có chắc muốn xoá toàn bộ số lượng đã quét để quét lại từ đầu không?")) {
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
                if (!this.isDestroyed) {
                    await this.loadPicking();
                }
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
                await this.loadPicking();
            } else {
                if (res.warning) {
                    this.playSound('error');
                    this.notification.add(res.warning, { type: "warning" });
                }
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
                await this.loadPicking();
            } else {
                if (res.warning) {
                    this.playSound('error');
                    this.notification.add(res.warning, { type: "warning" });
                }
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
                if (res.backorder_created) {
                    this.notification.add(`Xác nhận thành công. Nhấn vào mã đơn dưới đây để xem đơn tách kiện:`, { 
                        type: "info",
                        sticky: true,
                        buttons: [
                            {
                                name: res.backorder_name,
                                onClick: () => {
                                    this.actionService.doAction({
                                        type: 'ir.actions.act_window',
                                        res_model: 'stock.picking',
                                        res_id: res.backorder_id,
                                        views: [[false, 'form']],
                                        target: 'current',
                                    });
                                },
                                primary: true,
                            }
                        ]
                    });
                } else {
                    this.notification.add("Xác nhận phiếu thành công!", { type: "success" });
                }
                this.playSound('success');
                await this.loadPicking();
            }
        } catch (e) {
            this.notification.add("Lỗi kết nối", { type: "danger" });
        }
    }
    
    async unpackPackage(pkg) {
        if (!confirm(`Bạn có chắc chắn muốn gỡ đóng gói kiện "${pkg.name}" thành hàng lẻ không?`)) {
            return;
        }
        this.state.loading = true;
        try {
            const res = await rpc("/hlv_mobile_barcode/unpack_package", {
                picking_id: this.props.pickingId,
                package_id: pkg.id
            });
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                this.notification.add("Đã gỡ đóng gói thành công", { type: "success" });
                this.playSound('success');
                await this.loadPicking();
            }
        } catch (e) {
            this.notification.add("Lỗi kết nối", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async togglePackages() {
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
        try {
            if (navigator.vibrate) {
                if (type === 'success') {
                    navigator.vibrate(150);
                } else if (type === 'error') {
                    navigator.vibrate([100, 50, 100]);
                }
            }
        } catch (e) {}
    }
}
