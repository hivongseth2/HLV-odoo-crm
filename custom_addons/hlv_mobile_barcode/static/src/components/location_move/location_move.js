/** @odoo-module **/

import { Component, useState, onWillStart, onMounted, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

export class LocationMove extends Component {
    static template = "hlv_mobile_barcode.LocationMove";
    static props = {
        productId: Number,
        prefillLocationBarcode: { type: String, optional: true },
        prefillLocationName: { type: String, optional: true },
        sourceQty: { type: Number, optional: true },
        productName: { type: String, optional: true },
        destWarehouseId: { type: [Number, Boolean], optional: true },
        destLocationId: { type: [Number, Boolean], optional: true },
        onBack: Function,
        onSuccess: { type: Function, optional: true },
        registerScanner: { type: Function, optional: true },
    };

    setup() {
        this.action = useService("action");
        this.notification = useService("notification");
        this.destLocationInputRef = useRef("destLocationInput");
        
        this.state = useState({
            productName: this.props.productName || "Loading...",
            productBarcode: "",
            sourceLocationBarcode: this.props.prefillLocationBarcode || "",
            sourceLocationName: this.props.prefillLocationName || "",
            destLocationBarcode: "",
            destLocationName: "",
            destLocationId: false,
            destLocationInput: "",
            qty: 0,
            loading: false,
            inFlight: false,
        });

        this.localScanner = null;

        onWillStart(async () => {
            if (!this.props.productName) {
                try {
                    const product = await rpc("/web/dataset/call_kw/product.product/read", {
                        model: 'product.product',
                        method: 'read',
                        args: [[this.props.productId], ['display_name', 'barcode']],
                        kwargs: {}
                    });
                    if (product && product.length) {
                        this.state.productName = product[0].display_name;
                        this.state.productBarcode = product[0].barcode || "";
                    } else {
                        this.state.productName = "Unknown Product";
                    }
                } catch(e) {
                    this.state.productName = "Product #" + this.props.productId;
                }
            } else {
                // Fetch product barcode for comparison
                try {
                    const product = await rpc("/web/dataset/call_kw/product.product/read", {
                        model: 'product.product',
                        method: 'read',
                        args: [[this.props.productId], ['barcode']],
                        kwargs: {}
                    });
                    if (product && product.length) {
                        this.state.productBarcode = product[0].barcode || "";
                    }
                } catch(e) {}
            }
            
            if (this.props.registerScanner) {
                this.props.registerScanner(this.handleScannedBarcode.bind(this));
            }
        });

        onMounted(() => {
            this.focusScanInput();
        });
    }

    focusScanInput(delay = 50) {
        setTimeout(() => {
            const input = this.destLocationInputRef?.el;
            if (!input) return;
            input.focus({ preventScroll: true });
            const pos = input.value ? input.value.length : 0;
            try {
                input.setSelectionRange(pos, pos);
            } catch (e) {}
        }, delay);
    }

    onDestLocationInputKeyup(ev) {
        if (ev.key === 'Enter' && this.state.destLocationInput) {
            this.handleScannedBarcode(this.state.destLocationInput);
            this.state.destLocationInput = "";
            this.focusScanInput();
        }
    }

    async handleScannedBarcode(decodedText) {
        const now = Date.now();
        if (this.lastScannedBarcode === decodedText && this.lastScannedTime && now - this.lastScannedTime < 500) {
            return; // Debounce to prevent double events (from both BarcodeScanner and Enter keyup)
        }
        this.lastScannedBarcode = decodedText;
        this.lastScannedTime = now;

        if (this.state.productBarcode && decodedText === this.state.productBarcode) {
            if (this.state.qty >= this.props.sourceQty) {
                this.playSound('error');
                this.notification.add(`Vượt quá số lượng tồn tại vị trí này (${this.props.sourceQty})`, { type: "warning" });
            } else {
                this.state.qty += 1;
                this.playSound('success');
                this.notification.add(`Đã tăng số lượng lên ${this.state.qty}`, { type: "success" });
            }
        } else {
            try {
                const res = await rpc("/hlv_mobile_barcode/smart_scan", { barcode: decodedText });
                if (res && res.type === 'product' && res.id === this.props.productId) {
                    if (this.state.qty >= this.props.sourceQty) {
                        this.playSound('error');
                        this.notification.add(`Vượt quá số lượng tồn tại vị trí này (${this.props.sourceQty})`, { type: "warning" });
                    } else {
                        this.state.qty += 1;
                        this.playSound('success');
                        this.notification.add(`Đã tăng số lượng lên ${this.state.qty}`, { type: "success" });
                    }
                } else if (res && res.type === 'location') {
                    this.state.destLocationBarcode = decodedText;
                    this.state.destLocationName = res.name;
                    this.state.destLocationId = res.id;
                    this.state.destLocationInput = "";
                    this.playSound('success');
                    this.notification.add(`Đã nhận vị trí đích: ${res.name}`, { type: "success" });
                } else {
                    this.playSound('error');
                    this.notification.add("Mã vạch không hợp lệ", { type: "warning" });
                }
            } catch (e) {
                this.playSound('error');
                this.notification.add("Lỗi kết nối", { type: "danger" });
            }
        }
        this.focusScanInput();
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

    async doMove() {
        // Chặn double-click / Enter liên tục ngay từ đầu — inFlight được set đồng bộ,
        // không phụ thuộc vào OWL re-render.
        if (this.state.inFlight) return;
        if (!this.state.qty || this.state.qty <= 0) {
            this.notification.add("Số lượng chuyển không hợp lệ", { type: "danger" });
            return;
        }
        if (this.state.qty > this.props.sourceQty) {
            this.notification.add(`Số lượng chuyển không được vượt quá số lượng tồn (${this.props.sourceQty})`, { type: "danger" });
            return;
        }
        if (!this.state.destLocationBarcode) {
            this.notification.add("Vui lòng quét vị trí đích", { type: "danger" });
            return;
        }

        this.state.inFlight = true;
        this.state.loading = true;
        try {
            const res = await rpc("/hlv_mobile_barcode/move_location", {
                product_id: this.props.productId,
                source_barcode: this.state.sourceLocationBarcode,
                qty: this.state.qty,
                dest_warehouse_id: this.props.destWarehouseId || false,
                dest_location_id: this.state.destLocationId
            });

            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                this.notification.add("Chuyển kho thành công!", { type: "success" });
                if (this.props.onSuccess) {
                    this.props.onSuccess();
                } else {
                    this.props.onBack();
                }
            }
        } catch (e) {
            this.notification.add("Lỗi kết nối máy chủ", { type: "danger" });
        } finally {
            this.state.inFlight = false;
            this.state.loading = false;
        }
    }
}
