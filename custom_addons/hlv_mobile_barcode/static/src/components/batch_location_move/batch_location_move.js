/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

export class BatchLocationMove extends Component {
    static template = "hlv_mobile_barcode.BatchLocationMove";
    static props = {
        sourceLocationBarcode: String,
        sourceLocationName: String,
        onBack: Function,
        registerScanner: { type: Function, optional: true },
    };

    setup() {
        this.action = useService("action");
        this.notification = useService("notification");
        
        this.state = useState({
            lines: [], // array of { product_id, product_name, barcode, qty }
            barcodeInput: "",
            loading: false,
            inPickingName: "",
            showLocalCamera: false,
        });

        this.localScanner = null;

        onWillStart(async () => {
            if (this.props.registerScanner) {
                this.props.registerScanner(this.handleScannedBarcode.bind(this));
            }
        });
    }

    onBarcodeInputKeyup(ev) {
        if (ev.key === 'Enter') {
            this.onBarcodeInputEnter();
        }
    }

    onBarcodeInputEnter() {
        if (this.state.barcodeInput) {
            this.handleScannedBarcode(this.state.barcodeInput);
            this.state.barcodeInput = "";
        }
    }

    async handleScannedBarcode(decodedText) {
        // Find if this product barcode is already in the list
        const existingLine = this.state.lines.find(l => l.barcode === decodedText);
        
        if (existingLine) {
            existingLine.qty += 1;
            this.playSound('success');
            this.notification.add(`Đã tăng số lượng: ${existingLine.product_name} lên ${existingLine.qty}`, { type: "success" });
        } else {
            // Need to fetch product info
            this.state.loading = true;
            try {
                const res = await rpc("/hlv_mobile_barcode/smart_scan", { barcode: decodedText });
                if (res.error) {
                    this.playSound('error');
                    this.notification.add(res.error, { type: "danger" });
                } else if (res.type === 'product') {
                    this.state.lines.push({
                        product_id: res.id,
                        product_name: res.name,
                        barcode: decodedText,
                        qty: 1
                    });
                    this.playSound('success');
                    this.notification.add(`Đã thêm sản phẩm: ${res.name}`, { type: "success" });
                } else {
                    this.playSound('error');
                    this.notification.add("Mã vừa quét không phải là sản phẩm", { type: "warning" });
                }
            } catch (e) {
                this.playSound('error');
                this.notification.add("Lỗi kết nối", { type: "danger" });
            }
            this.state.loading = false;
        }
    }

    increaseQty(line) {
        line.qty += 1;
    }

    decreaseQty(line) {
        if (line.qty > 0) {
            line.qty -= 1;
        }
    }
    
    removeLine(lineIndex) {
        this.state.lines.splice(lineIndex, 1);
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
            this.localScanner = new window.Html5Qrcode("batch-location-move-camera-reader");
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
        const validLines = this.state.lines.filter(l => l.qty > 0);
        if (validLines.length === 0) {
            this.notification.add("Vui lòng quét ít nhất 1 sản phẩm với số lượng > 0", { type: "danger" });
            return;
        }
        
        this.state.loading = true;
        this.state.inPickingName = "";
        try {
            const linesPayload = validLines.map(l => ({
                product_id: l.product_id,
                qty: l.qty
            }));
            
            const res = await rpc("/hlv_mobile_barcode/move_location_batch", {
                source_barcode: this.props.sourceLocationBarcode,
                lines: linesPayload
            });
            
            if (res.error) {
                this.notification.add(res.error, { type: "danger" });
            } else {
                this.notification.add("Tạo lệnh chuyển hàng loạt thành công", { type: "success" });
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
