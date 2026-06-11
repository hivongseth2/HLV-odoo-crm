/** @odoo-module **/

import { Component, useState, onWillDestroy, useRef } from "@odoo/owl";

export class CameraScanner extends Component {
    static template = "hlv_barcode_shipper.CameraScanner";
    static props = {
        onBarcodeScanned: { type: Function },
        onClose: { type: Function },
    };

    setup() {
        this.videoRef = useRef("videoElement");
        this.state = useState({
            isRunning: false,
            error: null,
        });

        this._cameraStream = null;
        this._scanInterval = null;
        this._barcodeDetector = null;

        onWillDestroy(() => {
            this.stopCamera();
        });
    }

    async startCamera() {
        // Logic khởi chạy BarcodeDetector và MediaDevices
        // Sẽ copy từ barcode_scanner.js
        this.state.isRunning = true;
    }

    stopCamera() {
        this.state.isRunning = false;
        if (this._scanInterval) {
            clearInterval(this._scanInterval);
            this._scanInterval = null;
        }
        if (this._cameraStream) {
            this._cameraStream.getTracks().forEach(t => t.stop());
            this._cameraStream = null;
        }
    }

    onClose() {
        this.stopCamera();
        if (this.props.onClose) {
            this.props.onClose();
        }
    }
}
