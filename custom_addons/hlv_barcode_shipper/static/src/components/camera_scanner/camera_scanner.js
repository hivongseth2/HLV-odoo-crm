/** @odoo-module **/

import { Component, xml, useState, onWillDestroy, useRef } from "@odoo/owl";

export class CameraScanner extends Component {
    static template = xml`<div class="camera-section active">
            <div class="camera-reader">
                <video t-ref="videoElement" autoplay="1" playsinline="1" muted="1" style="width: 100%; max-height: 40vh; object-fit: cover; border-radius: 8px;"></video>
            </div>
            
            <t t-if="state.error">
                <div class="alert alert-danger mt-2"><t t-esc="state.error"/></div>
            </t>

            <div class="camera-controls mt-2 text-center">
                <button t-if="!state.isRunning" class="btn btn-primary btn-sm" t-on-click="startCamera">
                    <i class="fa fa-camera"></i> Mở Camera
                </button>
                <button t-else="" class="btn btn-secondary btn-sm" t-on-click="onClose">
                    <i class="fa fa-times"></i> Đóng Camera
                </button>
            </div>
        </div>`;
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
