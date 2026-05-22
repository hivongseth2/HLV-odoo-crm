/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

export class LocationMove extends Component {
    static template = "hlv_mobile_barcode.LocationMove";
    static props = {
        productId: Number,
        onBack: Function,
        openCameraForInput: { type: Function, optional: true },
    };

    setup() {
        this.notification = useService("notification");
        
        this.state = useState({
            productName: "Loading...",
            productBarcode: "",
            sourceLocationBarcode: "",
            sourceLocationName: "",
            locationInput: "",
            qty: 1,
            loading: false,
            inPickingName: "",
            showLocalCamera: false,
        });

        this.localScanner = null;

        onWillStart(async () => {
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
            
            if (this.props.registerScanner) {
                this.props.registerScanner(this.handleScannedBarcode.bind(this));
            }
        });
    }

    onLocationInputKeyup(ev) {
        if (ev.key === 'Enter' && this.state.locationInput) {
            this.handleScannedBarcode(this.state.locationInput);
            this.state.locationInput = "";
        }
    }

    async handleScannedBarcode(decodedText) {
        if (!this.state.sourceLocationBarcode) {
            if (this.state.productBarcode && decodedText === this.state.productBarcode) {
                this.playSound('error');
                this.notification.add("Vui lòng quét vị trí lấy hàng trước khi quét sản phẩm", { type: "danger" });
            } else {
                try {
                    const res = await rpc("/hlv_mobile_barcode/validate_location", { barcode: decodedText });
                    if (res.error) {
                        this.playSound('error');
                        this.notification.add(res.error, { type: "danger" });
                    } else {
                        this.state.sourceLocationBarcode = res.location_barcode;
                        this.state.sourceLocationName = res.location_name;
                        this.playSound('success');
                        this.notification.add("Đã nhận vị trí: " + res.location_name, { type: "success" });
                    }
                } catch (e) {
                    this.playSound('error');
                    this.notification.add("Lỗi kết nối", { type: "danger" });
                }
            }
        } else {
            if (this.state.productBarcode && decodedText === this.state.productBarcode) {
                this.state.qty += 1;
                this.playSound('success');
                this.notification.add("Đã tăng số lượng lên " + this.state.qty, { type: "success" });
            } else {
                try {
                    const res = await rpc("/hlv_mobile_barcode/validate_location", { barcode: decodedText });
                    if (res.error) {
                        this.playSound('error');
                        this.notification.add(res.error, { type: "danger" });
                    } else {
                        this.state.sourceLocationBarcode = res.location_barcode;
                        this.state.sourceLocationName = res.location_name;
                        this.playSound('success');
                        this.notification.add("Đã đổi vị trí thành: " + res.location_name, { type: "success" });
                    }
                } catch (e) {
                    this.playSound('error');
                    this.notification.add("Lỗi kết nối", { type: "danger" });
                }
            }
        }
    }

    async openLocalCamera() {
        this.state.showLocalCamera = true;
        await new Promise(r => setTimeout(r, 100)); // wait for DOM element

        if (!window.Html5Qrcode) {
            try {
                await new Promise((resolve, reject) => {
                    const script = document.createElement("script");
                    script.src = "https://unpkg.com/html5-qrcode";
                    script.onload = resolve;
                    script.onerror = reject;
                    document.head.appendChild(script);
                });
            } catch (e) {
                this.notification.add("Không thể tải thư viện camera.", { type: "danger" });
                this.state.showLocalCamera = false;
                return;
            }
        }

        try {
            this.localScanner = new window.Html5Qrcode("location-move-camera-reader");
            await this.localScanner.start(
                { facingMode: "environment" },
                { fps: 15, disableFlip: false, aspectRatio: 1.0 },
                async (decodedText) => {
                    this.handleScannedBarcode(decodedText);
                },
                (errorMessage) => {}
            );
        } catch (err) {
            this.notification.add("Lỗi mở Camera: " + err, { type: "warning" });
            this.closeLocalCamera();
        }
    }

    async closeLocalCamera() {
        if (this.localScanner) {
            try {
                await this.localScanner.stop();
                this.localScanner.clear();
            } catch(e) {}
            this.localScanner = null;
        }
        this.state.showLocalCamera = false;
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

    async doMove() {
        if (!this.state.sourceLocationBarcode) {
            if (this.state.locationInput) {
                await this.handleScannedBarcode(this.state.locationInput);
                this.state.locationInput = "";
                if (!this.state.sourceLocationBarcode) return;
            } else {
                this.notification.add("Yêu cầu nhập vị trí lấy hàng", { type: "danger" });
                return;
            }
        }
        
        this.state.loading = true;
        this.state.inPickingName = "";
        try {
            const res = await rpc("/hlv_mobile_barcode/move_location", {
                product_id: this.props.productId,
                source_barcode: this.state.sourceLocationBarcode,
                qty: this.state.qty
            });
            
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                this.notification.add("Tạo lệnh chuyển thành công", { type: "success" });
                if (res.in_picking_name) {
                    this.state.inPickingName = res.in_picking_name;
                } else {
                    this.props.onBack();
                }
            }
        } catch (e) {
            this.notification.add("Lỗi kết nối máy chủ", { type: "danger" });
        }
        this.state.loading = false;
    }
}
