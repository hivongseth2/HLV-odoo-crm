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
            sourceLocationBarcode: "",
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
                    args: [[this.props.productId], ['display_name']],
                    kwargs: {}
                });
                if (product && product.length) {
                    this.state.productName = product[0].display_name;
                } else {
                    this.state.productName = "Unknown Product";
                }
            } catch(e) {
                this.state.productName = "Product #" + this.props.productId;
            }
        });
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
                    this.state.sourceLocationBarcode = decodedText;
                    this.playSound('success');
                    await this.closeLocalCamera();
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
            this.notification.add("Yêu cầu nhập vị trí lấy hàng", { type: "danger" });
            return;
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
