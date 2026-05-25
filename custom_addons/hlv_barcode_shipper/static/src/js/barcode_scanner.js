// hlv_barcode_shipper/static/src/js/barcode_scanner.js
/**
 * HLV Barcode Shipper JavaScript
 * Supports 3 tabs: Nhận hàng / Giao hàng / Trả hàng
 * Supports hardware barcode scanner (keyboard Enter) + camera (BarcodeDetector API + ZXing WASM fallback)
 */

class BarcodeShipper {
    constructor() {
        // ---- Deliver state ----
        this.pickingDataMap = {};
        this.soGroups = [];
        this.activePickingId = null;
        this.customerName = '';
        this.scannedBarcodes = new Set();

        // ---- Receive state ----
        this.receivePickingIds = [];
        this.receiveItems = null;
        this.receiveSoGroups = [];
        this.receiveAvailableData = {};   // id -> { info, items }
        this.receiveSelectedIds = new Set();
        this.receiveExpandedPickingIds = new Set();
        this.receiveLoadOffset = 0;
        this.receiveLoadTotal = 0;
        this.receiveHasMore = false;

        // ---- Return state ----
        this.returnPickings = [];
        this.returnSelectedIds = new Set();
        this.returnPickingId = null;
        this.returnReason = '';
        this.returnDetailItems = null;
        this.returnExpandedIds = new Set();
        this.returnItemCache = {};

        // ---- Camera state ----
        this._cameraStream = null;
        this._scanInterval = null;
        this._barcodeDetector = null;
        this.isCameraRunning = false;
        this.currentCameraSection = null;
        this.currentCameraMode = null;
        this._lastScanResult = '';
        this._lastScanTime = 0;

        // ---- Photo camera state ----
        this._photoCameraStream = null;
        this._photoBlob = null;
        this._photoPickingIds = [];
        this._capturedPhotos = [];      // [{pickingId, pickingName, blob}]
        this._photoNameToId = {};       // {so_name(origin) → picking_id}
        this._photoDetectedPickingId = null;
        this._photoQrLoopTimer = null;
        this._photoQrDetectedAt = 0;    // timestamp để debounce reset detected ID

        // ---- Settings ----
        this.settings = {
            skip_package_scan: false,
            skip_product_scan: false,
            receive_require_detail_scan: false,
            receive_skip_package_scan: false,
            receive_skip_product_scan: false,
            return_require_detail_scan: false,
            return_skip_package_scan: false,
            return_skip_product_scan: false,
        };

        this.sessionId = this.generateSessionId();
        this.init();
    }

    generateSessionId() {
        return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    async init() {
        await this.loadSettings();
        this.bindEvents();
        this.setupBarcodeInputs();
        this.switchTab('receive');
        this.loadReturnList();

        window.addEventListener('beforeunload', (e) => {
            if (Object.keys(this.pickingDataMap).length > 0) {
                const msg = '⚠️ CẢNH BÁO: Tiến độ quét sẽ bị MẤT nếu bạn tải lại trang!';
                e.preventDefault();
                e.returnValue = msg;
                return msg;
            }
        });

        // Auto-refocus input khi click bất kỳ đâu trên trang
        // để người dùng luôn có thể quét barcode ngay lập tức
        document.addEventListener('click', (e) => {
            const target = e.target;
            // Không refocus nếu đang click vào input, button, modal, hoặc camera
            if (target.closest('input, textarea, button, .btn, .modal-overlay.show, .camera-section.active, select')) return;
            this.focusCurrentInput();
        });

        // Refocus định kỳ mỗi 2 giây (safety net cho trường hợp mất focus)
        this._refocusInterval = setInterval(() => {
            const active = document.activeElement;
            // Chỉ refocus nếu focus hiện tại không phải là input/textarea/button
            if (!active || (active.tagName !== 'INPUT' && active.tagName !== 'TEXTAREA' && active.tagName !== 'SELECT' && !active.closest('button, .btn'))) {
                // Không refocus nếu modal đang mở
                if (!document.querySelector('.modal-overlay.show')) {
                    this.focusCurrentInput();
                }
            }
        }, 2000);
    }

    async loadSettings() {
        try {
            const res = await this.apiCall('/api/barcode/get_settings', {});
            if (res && res.success && res.settings) {
                this.settings = { ...this.settings, ...res.settings };
            }
        } catch (e) {
            console.warn('Failed to load settings, using defaults');
        }
    }

    // ========================= TAB MANAGEMENT =========================

    switchTab(tabName) {
        this.stopCamera();
        this._stopPhotoCamera();
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabName);
        });
        document.querySelectorAll('.tab-content').forEach(tc => {
            tc.classList.toggle('active', tc.id === `tab-${tabName}`);
        });
        if (tabName === 'receive') {
            this.showReceiveStep('receive-step-scan');
            this._showReceivePrompt();
        } else if (tabName === 'deliver') {
            this.showDeliverStep('step-scan-pick');
        } else if (tabName === 'return') {
            this.showReturnStep('return-step-list');
            this.loadReturnList();
        } else if (tabName === 'delivered') {
            const dateInput = document.getElementById('delivered-date-filter');
            this.loadDeliveredList(dateInput?.value || '');
        }
    }

    showDeliverStep(id) {
        document.querySelectorAll('#tab-deliver .scan-step').forEach(s => s.classList.remove('active'));
        const step = document.getElementById(id);
        if (step) { step.classList.add('active'); this.focusCurrentInput(); }
    }

    showReceiveStep(id) {
        document.querySelectorAll('#tab-receive .scan-step').forEach(s => s.classList.remove('active'));
        const step = document.getElementById(id);
        if (step) { step.classList.add('active'); this.focusCurrentInput(); }
    }

    showReturnStep(id) {
        document.querySelectorAll('#tab-return .scan-step').forEach(s => s.classList.remove('active'));
        const step = document.getElementById(id);
        if (step) { step.classList.add('active'); this.focusCurrentInput(); }
    }

    // Backward-compat alias for deliver tab
    showStep(id) { this.showDeliverStep(id); }

    bindEvents() {
        // Tab switching
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => this.switchTab(btn.dataset.tab));
        });

        // === DELIVER TAB ===
        document.getElementById('scan-pick-btn')?.addEventListener('click', () => this.scanPickOrder());
        document.getElementById('scan-item-btn')?.addEventListener('click', () => this.scanItem());
        document.getElementById('complete-all-btn')?.addEventListener('click', () => this.completeAllDelivery());
        document.getElementById('reset-scan-btn')?.addEventListener('click', () => this.resetScan());
        document.getElementById('new-delivery-btn')?.addEventListener('click', () => this.startNewDelivery());
        document.getElementById('btn-open-camera-pick')?.addEventListener('click', () => this.startCamera('camera-pick', 'reader-pick', 'pick'));
        document.getElementById('btn-open-camera-item')?.addEventListener('click', () => this.startCamera('camera-item', 'reader-item', 'item'));

        // === PHOTO STEP ===
        document.getElementById('photo-open-camera-btn')?.addEventListener('click', () => this._startPhotoCamera());
        document.getElementById('photo-capture-btn')?.addEventListener('click', () => this._capturePhoto());
        document.getElementById('photo-close-camera-btn')?.addEventListener('click', () => {
            this._stopPhotoCamera();
            document.getElementById('photo-open-section').style.display = 'block';
        });
        document.getElementById('photo-retake-btn')?.addEventListener('click', () => {
            this._photoBlob = null;
            this._photoDetectedPickingId = null;
            document.getElementById('photo-preview-section').style.display = 'none';
            document.getElementById('photo-send-btn').style.display = 'none';
            document.getElementById('photo-open-section').style.display = 'block';
            this.clearMessage('photo-result');
        });
        document.getElementById('photo-confirm-btn')?.addEventListener('click', () => this._confirmCapturedPhoto());
        document.getElementById('photo-file-input')?.addEventListener('change', (e) => {
            const file = e.target.files && e.target.files[0];
            if (file) this._handlePhotoFile(file);
        });
        document.getElementById('photo-send-btn')?.addEventListener('click', () => this.sendPhotoAndComplete());
        document.getElementById('photo-skip-btn')?.addEventListener('click', () => this.skipPhotoAndComplete());

        // === RECEIVE TAB ===
        document.getElementById('receive-scan-btn')?.addEventListener('click', () => {
            const q = document.getElementById('receive-barcode-input')?.value?.trim() || '';
            this.searchReceivePickings(q);
        });
        document.getElementById('btn-close-camera-receive')?.addEventListener('click', () => this.stopCamera());
        document.getElementById('confirm-receive-selected-btn')?.addEventListener('click', () => this.confirmReceiveSelected());
        document.getElementById('receive-detail-scan-btn')?.addEventListener('click', () => this.scanReceiveDetail());
        document.getElementById('confirm-receive-btn')?.addEventListener('click', () => this.confirmReceive());
        document.getElementById('receive-back-btn')?.addEventListener('click', () => {
            this.stopCamera();
            this.receivePickingIds = [];
            this.receiveItems = null;
            this.showReceiveStep('receive-step-scan');
        });
        document.getElementById('btn-open-camera-receive')?.addEventListener('click', () => this.startCamera('camera-receive', 'reader-receive', 'receive'));
        document.getElementById('btn-open-camera-receive-detail')?.addEventListener('click', () => this.startCamera('camera-receive-detail', 'reader-receive-detail', 'receive-detail'));

        // === RETURN TAB ===
        document.getElementById('confirm-return-btn')?.addEventListener('click', () => this.confirmReturn());
        document.getElementById('return-select-all-btn')?.addEventListener('click', () => this.toggleReturnSelectAll());
        document.getElementById('return-scan-btn')?.addEventListener('click', () => this.scanReturnPicking());
        document.getElementById('return-scan-input')?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); this.scanReturnPicking(); }
        });
        document.getElementById('btn-open-camera-return-scan')?.addEventListener('click', () => this.startCamera('camera-return-scan', 'reader-return-scan', 'return-scan'));
        document.getElementById('return-detail-scan-btn')?.addEventListener('click', () => this.scanReturnDetail());
        document.getElementById('confirm-return-detail-btn')?.addEventListener('click', () => this.confirmReturnDetail());
        document.getElementById('return-detail-back-btn')?.addEventListener('click', () => {
            this.stopCamera();
            this.showReturnStep('return-step-list');
        });
        document.getElementById('btn-open-camera-return-detail')?.addEventListener('click', () => this.startCamera('camera-return-detail', 'reader-return-detail', 'return-detail'));

        // Common
        document.getElementById('show-history-btn')?.addEventListener('click', () => this.showHistory());
        document.getElementById('help-btn')?.addEventListener('click', () => this.showHelp());

        // === DELIVERED TAB ===
        document.getElementById('delivered-filter-btn')?.addEventListener('click', () => {
            const dateInput = document.getElementById('delivered-date-filter');
            this.loadDeliveredList(dateInput?.value || '');
        });
        document.getElementById('delivered-clear-btn')?.addEventListener('click', () => {
            const dateInput = document.getElementById('delivered-date-filter');
            if (dateInput) dateInput.value = '';
            this.loadDeliveredList();
        });
        // Set today as default
        const dateInput = document.getElementById('delivered-date-filter');
        if (dateInput) dateInput.value = new Date().toISOString().slice(0, 10);

        document.querySelectorAll('.modal-close').forEach(btn => {
            btn.addEventListener('click', e => this.closeModal(e.target.closest('.modal-overlay')));
        });
        document.querySelectorAll('.modal-overlay').forEach(modal => {
            modal.addEventListener('click', e => {
                if (e.target === modal) this.closeModal(modal);
            });
        });
    }

    setupBarcodeInputs() {
        const inputs = [
            ['pick-barcode-input', () => this.scanPickOrder()],
            ['item-barcode-input', () => this.scanItem()],
            ['receive-barcode-input', () => {
                const q = document.getElementById('receive-barcode-input')?.value?.trim() || '';
                this.searchReceivePickings(q);
            }],
            ['receive-detail-barcode-input', () => this.scanReceiveDetail()],
            ['return-detail-barcode-input', () => this.scanReturnDetail()],
        ];
        inputs.forEach(([id, handler]) => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener('keypress', e => {
                    if (e.key === 'Enter') { e.preventDefault(); handler(); }
                });
            }
        });
        this.focusCurrentInput();
    }

    focusCurrentInput() {
        setTimeout(() => {
            const activeTab = document.querySelector('.tab-content.active');
            const activeStep = activeTab && activeTab.querySelector('.scan-step.active');
            const input = activeStep && activeStep.querySelector('.form-control');
            if (input) { input.focus(); input.select(); }
        }, 100);
    }

    showStep(id) {
        document.querySelectorAll('.scan-step').forEach(s => s.classList.remove('active'));
        const step = document.getElementById(id);
        if (step) {
            step.classList.add('active');
            this.focusCurrentInput();

            // Auto-start camera based on step
            if (id === 'step-scan-pick') {
                this.startCamera('camera-pick', 'reader-pick', 'pick');
            } else if (id === 'step-scan-items') {
                this.startCamera('camera-item', 'reader-item', 'item');
            } else {
                this.stopCamera();
            }
        } else {
            this.stopCamera();
        }
    }

    showMessage(id, message, type = 'success') {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = message;
        el.className = `alert show alert-${type}`;
        if (type === 'success') {
            setTimeout(() => el.classList.remove('show'), 4000);
        }
    }

    clearMessage(id) {
        const el = document.getElementById(id);
        if (el) el.classList.remove('show');
    }

    playSound(type = 'success') {
        // 1. Vibration
        if (navigator.vibrate) {
            if (type === 'success') navigator.vibrate(200);
            else navigator.vibrate([100, 50, 100]);
        }

        // 2. Sound (AudioContext)
        try {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (!AudioContext) return;

            const ctx = new AudioContext();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();

            osc.connect(gain);
            gain.connect(ctx.destination);

            if (type === 'success') {
                osc.type = 'sine';
                osc.frequency.value = 1000; // 1000Hz beep
                gain.gain.value = 0.1;
                osc.start();
                osc.stop(ctx.currentTime + 0.15); // 150ms
            } else {
                osc.type = 'sawtooth';
                osc.frequency.value = 200; // Low buzz
                gain.gain.value = 0.1;
                osc.start();
                osc.stop(ctx.currentTime + 0.3);
            }
        } catch (e) {
            console.warn('Audio play failed:', e);
        }
    }

    // ========================= CAMERA =========================

    async _initBarcodeDetector() {
        if (this._barcodeDetector) return;
        // BarcodeDetector is always available:
        // - Native on Chrome 83+ (Android), Safari 17.2+ (iOS)
        // - Polyfilled by barcode-detector@3 (ZXing C++ WASM) on older browsers
        if (typeof BarcodeDetector === 'undefined') {
            console.error('[Scanner] BarcodeDetector not available. Polyfill may have failed to load.');
            return;
        }
        try {
            this._barcodeDetector = new BarcodeDetector({
                formats: [
                    'code_128', 'code_39', 'ean_13', 'ean_8',
                    'upc_a', 'upc_e', 'itf', 'qr_code',
                    'data_matrix', 'codabar'
                ]
            });
            console.log('[Scanner] BarcodeDetector ready');
        } catch (e) {
            console.error('[Scanner] BarcodeDetector init failed:', e);
        }
    }

    async startCamera(sectionId, readerId, mode) {
        if (this.isCameraRunning && this.currentCameraSection === sectionId) return;
        if (this.isCameraRunning) await this.stopCamera();

        await this._initBarcodeDetector();

        const section = document.getElementById(sectionId);
        if (section) section.classList.add('active');
        this.currentCameraSection = sectionId;
        this.currentCameraMode = mode;

        const btnMap = {
            'pick': 'btn-open-camera-pick',
            'item': 'btn-open-camera-item',
            'receive': 'btn-open-camera-receive',
            'receive-detail': 'btn-open-camera-receive-detail',
            'return-detail': 'btn-open-camera-return-detail',
            'return-scan': 'btn-open-camera-return-scan',
        };
        const btnId = btnMap[mode];
        if (btnId) {
            const btn = document.getElementById(btnId);
            if (btn) btn.style.display = 'none';
        }

        const readerEl = document.getElementById(readerId);
        if (!readerEl) return;
        readerEl.innerHTML = '';

        // Create video element
        const video = document.createElement('video');
        video.setAttribute('autoplay', '');
        video.setAttribute('playsinline', '');
        video.setAttribute('muted', '');
        video.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;display:block;';
        readerEl.appendChild(video);

        // Add scan overlay with laser line
        const overlay = document.createElement('div');
        overlay.className = 'scan-overlay';
        overlay.innerHTML = '<div class="scan-laser"></div>';
        readerEl.style.cssText = 'position:relative;width:100%;height:250px;overflow:hidden;background:#000;';
        readerEl.appendChild(overlay);

        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: { ideal: 'environment' },
                    width: { ideal: 1280 },
                    height: { ideal: 720 },
                    focusMode: { ideal: 'continuous' },
                    frameRate: { ideal: 30 },
                },
                audio: false
            });
            this._cameraStream = stream;
            video.srcObject = stream;
            await video.play();
            // Re-enforce absolute positioning after play() — mobile resets video layout
            video.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;display:block;';
            this.isCameraRunning = true;
            this._lastScanResult = '';
            this._lastScanTime = 0;

            // Start scanning loop
            const scanFrame = async () => {
                if (!this.isCameraRunning || !this._cameraStream) return;
                if (video.readyState < video.HAVE_ENOUGH_DATA) {
                    this._scanInterval = requestAnimationFrame(scanFrame);
                    return;
                }

                try {
                    let result = null;
                    if (this._barcodeDetector) {
                        const barcodes = await this._barcodeDetector.detect(video);
                        if (barcodes.length > 0) result = barcodes[0].rawValue;
                    }

                    if (result) {
                        const now = Date.now();
                        // Deduplicate: same barcode within 2s
                        if (result !== this._lastScanResult || (now - this._lastScanTime) > 2000) {
                            this._lastScanResult = result;
                            this._lastScanTime = now;
                            this.onScanSuccess(result, mode);
                        }
                    }
                } catch (e) { /* scan error, continue */ }

                // Next frame (~15fps scan rate to save CPU)
                setTimeout(() => {
                    this._scanInterval = requestAnimationFrame(scanFrame);
                }, 66);
            };
            this._scanInterval = requestAnimationFrame(scanFrame);

        } catch (err) {
            console.error('[Scanner] Camera error:', err);
            if (btnId) {
                const btn = document.getElementById(btnId);
                if (btn) btn.style.display = 'block';
            }
            if (section) section.classList.remove('active');
        }
    }

    async stopCamera() {
        this.isCameraRunning = false;
        if (this._scanInterval) {
            cancelAnimationFrame(this._scanInterval);
            this._scanInterval = null;
        }
        if (this._cameraStream) {
            this._cameraStream.getTracks().forEach(t => t.stop());
            this._cameraStream = null;
        }
        this.currentCameraSection = null;
        this.currentCameraMode = null;

        // Clean up video elements
        document.querySelectorAll('.camera-section').forEach(el => {
            el.classList.remove('active');
            const reader = el.querySelector('.camera-reader, [id^="reader-"]');
            if (reader) reader.innerHTML = '';
        });
        ['btn-open-camera-pick', 'btn-open-camera-item', 'btn-open-camera-receive',
            'btn-open-camera-receive-detail', 'btn-open-camera-return-detail', 'btn-open-camera-return-scan'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) btn.style.display = 'block';
        });
    }

    onScanSuccess(decodedText, mode) {
        if (mode === 'pick') {
            const input = document.getElementById('pick-barcode-input');
            if (input) { input.value = decodedText; this.scanPickOrder(); }
        } else if (mode === 'item') {
            const input = document.getElementById('item-barcode-input');
            if (input) { input.value = decodedText; this.scanItem(); }
        } else if (mode === 'receive') {
            const input = document.getElementById('receive-barcode-input');
            if (input) input.value = decodedText;
            this.searchReceivePickings(decodedText);
        } else if (mode === 'receive-detail') {
            const input = document.getElementById('receive-detail-barcode-input');
            if (input) { input.value = decodedText; this.scanReceiveDetail(); }
        } else if (mode === 'return-detail') {
            const input = document.getElementById('return-detail-barcode-input');
            if (input) { input.value = decodedText; this.scanReturnDetail(); }
        } else if (mode === 'return-scan') {
            const input = document.getElementById('return-scan-input');
            if (input) input.value = decodedText;
            this.scanReturnPicking();
        }
    }

    // --- API & Logic ---

    async scanPickOrder() {
        const input = document.getElementById('pick-barcode-input');
        const barcode = (input?.value || '').trim();
        if (!barcode) {
            this.showMessage('pick-result', 'Vui lòng nhập mã PICK', 'danger');
            return;
        }
        if (input) input.value = '';

        this.showMessage('pick-result', 'Đang tìm phiếu giao hàng...', 'warning');
        try {
            const res = await this.apiCall('/api/barcode/scan_pick', { barcode });
            if (res.success) {
                this.customerName = res.customer_name || 'Khách hàng';
                // Show modal with SO groups
                if (res.so_groups && res.so_groups.length > 0) {
                    // Check total number of pickings
                    let totalPickings = 0;
                    let singlePickingId = null;
                    res.so_groups.forEach(g => {
                        if (g.pickings) {
                            totalPickings += g.pickings.length;
                            if (g.pickings.length > 0) singlePickingId = g.pickings[0].id;
                        }
                    });

                    if (totalPickings === 1 && singlePickingId) {
                        this.showMessage('pick-result', 'Đã tìm thấy 1 phiếu, đang tải...', 'success');
                        this.loadMultipleOutDetails([singlePickingId]);
                    } else {
                        this.showPickingSelectionModal(res.so_groups);
                        this.showMessage('pick-result', res.message, 'success');
                    }
                } else {
                    this.showMessage('pick-result', 'Không tìm thấy nhóm phiếu nào.', 'danger');
                }
            } else {
                this.showMessage('pick-result', res.error || 'Không tìm thấy', 'danger');
                this.playSound('error');
                this.focusCurrentInput();
            }
        } catch (e) {
            console.error(e);
            this.showMessage('pick-result', 'Lỗi kết nối, vui lòng thử lại.', 'danger');
            this.playSound('error');
            this.focusCurrentInput();
        }
    }

    showPickingSelectionModal(soGroups) {
        let modal = document.getElementById('picking-selection-modal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'picking-selection-modal';
            modal.className = 'modal-overlay';
            modal.innerHTML = `
                <div class="modal-content" style="max-height: 80vh; overflow-y: auto;">
                    <div class="modal-header">
                        <h3>Chọn phiếu xuất kho</h3>
                        <button class="modal-close">&times;</button>
                    </div>
                    <div id="picking-selection-list" class="modal-body" style="padding: 10px; background: #f5f6f8;"></div>
                    <div class="modal-footer" style="padding: 15px; border-top: 1px solid #eee; background: #fff;">
                         <button id="confirm-selection-btn" class="btn btn-primary btn-block btn-lg">
                            Xác nhận chọn (<span id="selected-count">0</span>)
                         </button>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);

            modal.querySelector('.modal-close').addEventListener('click', () => this.closeModal(modal));
            modal.querySelector('#confirm-selection-btn').addEventListener('click', () => this.confirmSelection(modal));
        }

        const list = modal.querySelector('#picking-selection-list');
        list.innerHTML = '';

        // Add "Select All" Option
        const selectAllDiv = document.createElement('div');
        selectAllDiv.style.display = 'flex';
        selectAllDiv.style.justifyContent = 'space-between';
        selectAllDiv.style.alignItems = 'center';
        selectAllDiv.style.padding = '15px';
        selectAllDiv.style.marginBottom = '10px';
        selectAllDiv.style.background = '#fff';
        selectAllDiv.style.borderRadius = '12px';
        selectAllDiv.style.boxShadow = '0 2px 4px rgba(0,0,0,0.05)';

        selectAllDiv.innerHTML = `
            <label for="select-all-checkbox" style="font-weight: 700; font-size: 1rem; margin:0; color: #333;">Chọn tất cả</label>
            <input type="checkbox" id="select-all-checkbox" style="width: 24px; height: 24px;">
        `;
        list.appendChild(selectAllDiv);

        let allItemCheckboxes = [];

        soGroups.forEach(group => {
            if (group.so_name) {
                const groupTitle = document.createElement('div');
                groupTitle.className = 'selection-group-title';
                groupTitle.textContent = group.so_name;
                list.appendChild(groupTitle);
            }

            group.pickings.forEach(p => {
                const card = document.createElement('div');
                card.className = 'picking-select-card';
                if (p.is_related) card.classList.add('selected');
                card.dataset.id = p.id;

                card.innerHTML = `
                    <div class="card-info" style="flex: 1;">
                        <div class="card-name">${p.name}</div>
                        <div class="card-meta">
                           <i class="fa fa-calendar"></i> ${p.scheduled_date || ''} 
                           <span class="badge badge-info" style="margin-left: 5px;">${p.state}</span>
                        </div>
                    </div>
                    <div class="check-circle">
                         <i class="fa fa-check"></i>
                    </div>
                    <input type="checkbox" class="picking-checkbox" value="${p.id}" ${p.is_related ? 'checked' : ''} style="display: none;">
                `;

                // Card Click Event
                card.addEventListener('click', () => {
                    const cb = card.querySelector('.picking-checkbox');
                    cb.checked = !cb.checked;
                    if (cb.checked) card.classList.add('selected');
                    else card.classList.remove('selected');
                    updateCount();
                });

                list.appendChild(card);
                allItemCheckboxes.push(card.querySelector('.picking-checkbox'));
            });
        });

        // Select All Logic
        const selectAllCb = selectAllDiv.querySelector('#select-all-checkbox');

        selectAllCb.addEventListener('change', (e) => {
            const isChecked = e.target.checked;
            allItemCheckboxes.forEach(cb => {
                cb.checked = isChecked;
                const card = cb.closest('.picking-select-card');
                if (isChecked) card.classList.add('selected');
                else card.classList.remove('selected');
            });
            updateCount();
        });

        const updateCount = () => {
            const checkedCbs = modal.querySelectorAll('.picking-checkbox:checked');
            modal.querySelector('#selected-count').textContent = checkedCbs.length;

            // Update Select All state logic
            if (allItemCheckboxes.length > 0) {
                selectAllCb.checked = checkedCbs.length === allItemCheckboxes.length;
                selectAllCb.indeterminate = checkedCbs.length > 0 && checkedCbs.length < allItemCheckboxes.length;
            }
        };

        updateCount();
        this.showModal(modal);
    }

    async confirmSelection(modal) {
        const checkboxes = modal.querySelectorAll('.picking-checkbox:checked');
        const selectedIds = Array.from(checkboxes).map(cb => parseInt(cb.value));

        if (selectedIds.length === 0) {
            alert('Vui lòng chọn ít nhất một phiếu OUT!');
            return;
        }

        this.closeModal(modal);
        await this.loadMultipleOutDetails(selectedIds);
    }

    async loadMultipleOutDetails(pickingIds) {
        this.showMessage('pick-result', 'Đang tải thông tin...', 'warning');
        try {
            const res = await this.apiCall('/api/barcode/get_multiple_outs', {
                picking_ids: pickingIds
            });

            if (res.success) {
                this.pickingDataMap = {};
                this.soGroups = [];
                // Group response by SO again for the UI
                const soMap = {};

                res.data.forEach(d => {
                    const p = d.picking;
                    const items = (d.items || []).map(i => ({
                        ...i,
                        scanned_qty: i.scanned ? (i.qty || 0) : 0
                    }));

                    // Store details
                    this.pickingDataMap[p.id] = {
                        info: p,
                        items: items,
                        so_name: p.origin || 'Khác',
                        progress: this.calculateProgress(items)
                    };

                    // Group logic
                    const soName = p.origin || 'Khác';
                    if (!soMap[soName]) soMap[soName] = [];
                    soMap[soName].push(p.id);
                });

                this.soGroups = Object.keys(soMap).map(key => ({
                    name: key,
                    pickingIds: soMap[key]
                }));
                // Sort Groups
                this.soGroups.sort((a, b) => a.name.localeCompare(b.name));

                // Focus first picking
                if (pickingIds.length > 0) {
                    this.activePickingId = pickingIds[0];
                }

                this.renderAccordion();
                this.updateGlobalProgress();

                // Show Step 2
                document.getElementById('customer-name').textContent = this.customerName;
                document.getElementById('customer-info').style.display = 'block';
                this.showDeliverStep('step-scan-items');
                this.showMessage('pick-result', 'Đã tải xong dữ liệu.', 'success');
            } else {
                this.showMessage('pick-result', res.error || 'Lỗi tải dữ liệu', 'danger');
            }
        } catch (e) {
            console.error(e);
            this.showMessage('pick-result', 'Lỗi kết nối server', 'danger');
        }
    }

    calculateProgress(items) {
        const total = items.reduce((s, i) => s + (i.qty || 0), 0);
        const scanned = items.reduce((s, i) => s + (i.scanned_qty || 0), 0);
        return { total, scanned, percent: total ? (scanned / total * 100) : 0, isDone: scanned >= total && total > 0 };
    }

    renderAccordion() {
        const container = document.getElementById('so-accordion');
        if (!container) return;
        container.innerHTML = '';

        this.soGroups.forEach(group => {
            const groupEl = document.createElement('div');
            groupEl.className = 'so-group';
            // Auto expand if contains active picking
            if (group.pickingIds.includes(this.activePickingId)) {
                groupEl.classList.add('expanded');
            }

            // SO Header
            groupEl.innerHTML = `
                <div class="so-group-header">
                    <span class="so-name">${group.name}</span>
                    <span class="so-count">${group.pickingIds.length} phiếu</span>
                </div>
                <div class="so-group-content"></div>
            `;

            // Toggle Logic
            groupEl.querySelector('.so-group-header').addEventListener('click', () => {
                groupEl.classList.toggle('expanded');
            });

            const contentDiv = groupEl.querySelector('.so-group-content');

            group.pickingIds.forEach(pid => {
                const data = this.pickingDataMap[pid];
                const isDone = data.progress.isDone;
                const isActive = (pid === this.activePickingId);

                const outItem = document.createElement('div');
                outItem.className = `out-item ${isActive ? 'active' : ''}`;
                outItem.id = `out-${pid}`;

                outItem.innerHTML = `
                    <div class="out-item-header">
                        <div class="out-info-top">
                             <div class="out-name">${data.info.name}</div>
                             <div class="out-status-badge ${isDone ? 'done' : ''}">
                                ${isDone ? '<i class="fa fa-check"></i> Xong' : 'Đang chờ'}
                             </div>
                        </div>
                        <div class="out-mini-progress">
                             <div class="out-mini-progress-fill" style="width: ${data.progress.percent}%"></div>
                        </div>
                    </div>
                    <div class="out-item-content">
                        <!-- Items rendered here only if active -->
                    </div>
                `;

                // Click to activate
                outItem.querySelector('.out-item-header').addEventListener('click', (e) => {
                    e.stopPropagation(); // prevent closing SO group
                    this.setActivePicking(pid);
                });

                // Render items if active
                if (isActive) {
                    const itemContainer = outItem.querySelector('.out-item-content');
                    this.renderItemsList(itemContainer, data.items);
                }

                contentDiv.appendChild(outItem);
            });

            container.appendChild(groupEl);
        });
    }

    renderItemsList(container, items) {
        container.innerHTML = `<div id="items-list-${Date.now()}" class="items-list"></div>`;
        const listDiv = container.querySelector('.items-list');

        items.forEach(item => {
            const div = document.createElement('div');
            const isFull = (item.scanned_qty || 0) >= (item.qty || 0);
            div.className = `item-card ${isFull ? 'scanned' : ''}`;

            let icon = isFull
                ? '<i class="fa fa-check-circle" style="color: var(--success-color);"></i>'
                : (item.type === 'package' ? '<i class="fa fa-box"></i>' : '<i class="fa fa-cube"></i>');

            div.innerHTML = `
                <div class="item-info">
                    <div class="item-name">${item.name || ''}</div>
                    <div class="item-details" style="display: flex; gap: 10px; font-size: 0.8rem; color: #666;">
                        <span><i class="fa fa-barcode"></i> ${item.barcode}</span>
                        <span>SL: <b>${item.scanned_qty}/${item.qty}</b></span>
                    </div>
                </div>
                <div class="item-status-icon">${icon}</div>
            `;
            listDiv.appendChild(div);
        });
    }

    setActivePicking(pickingId) {
        if (this.activePickingId === pickingId) return;
        this.activePickingId = pickingId;
        this.renderAccordion();

        // Auto scroll to view (simple version)
        setTimeout(() => {
            const el = document.getElementById(`out-${pickingId}`);
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 100);
    }

    updateGlobalProgress() {
        let totalQty = 0;
        let scannedQty = 0;
        let allDone = true;

        Object.values(this.pickingDataMap).forEach(d => {
            totalQty += d.progress.total;
            scannedQty += d.progress.scanned;
            if (!d.progress.isDone) allDone = false;
        });

        const percent = totalQty ? (scannedQty / totalQty * 100) : 0;
        document.getElementById('global-progress-text').textContent = `${scannedQty} / ${totalQty}`;
        document.getElementById('global-progress-fill').style.width = `${percent}%`;

        const btn = document.getElementById('complete-all-btn');
        if (btn) btn.style.display = (allDone && totalQty > 0) ? 'block' : 'none';
    }

    async scanItem() {
        const input = document.getElementById('item-barcode-input');
        const barcode = (input?.value || '').trim();
        if (!barcode) {
            this.showMessage('item-result', 'Vui lòng nhập mã', 'danger');
            return;
        }

        // Logic: Search barcode in active picking FIRST.
        // If not found, searching in OTHER picked pickings? 
        // -> For now, let's strictly require scanning into the Active Picking 
        //    OR auto-switch if found in another picking?
        //    Auto-switching is better for UX.

        let targetPickingId = this.activePickingId;
        let itemFound = null;

        // 1. Check active picking first
        if (targetPickingId && this.pickingDataMap[targetPickingId]) {
            const items = this.pickingDataMap[targetPickingId].items;
            itemFound = items.find(i => i.barcode === barcode);
        }

        // 2. If not found, check other pickings
        if (!itemFound) {
            for (const pid of Object.keys(this.pickingDataMap)) {
                if (pid == this.activePickingId) continue; // skipped
                const items = this.pickingDataMap[pid].items;
                const match = items.find(i => i.barcode === barcode);
                if (match) {
                    targetPickingId = parseInt(pid);
                    itemFound = match;
                    break;
                }
            }
        }

        if (!itemFound) {
            this.showMessage('item-result', 'Mã không tìm thấy trong bất kỳ đơn nào đã chọn!', 'danger');
            this.playSound('error');
            if (input) { input.value = ''; input.focus(); }
            return;
        }

        // 3. Switch active if needed
        if (targetPickingId !== this.activePickingId) {
            this.setActivePicking(targetPickingId);
            // Notify user switched
            // this.showMessage('item-result', `Chuyển sang đơn ${this.pickingDataMap[targetPickingId].info.name}`, 'info');
        }

        // 4. Perform Update Logic (Client Side Optimistic)
        const pickingData = this.pickingDataMap[targetPickingId];
        let item = pickingData.items.find(i => i.barcode === barcode); // refind ref

        const maxQty = item.qty || 0;
        let newQty = item.scanned_qty || 0;

        if (newQty >= maxQty) {
            this.showMessage('item-result', 'Sản phẩm này đã đủ số lượng!', 'warning');
            this.playSound('error');
            if (input) { input.value = ''; input.focus(); }
            return;
        }

        if (item.type === 'package') {
            newQty = maxQty;
        } else {
            newQty += 1;
        }

        item.scanned_qty = newQty;

        // Recalculate picking progress
        pickingData.progress = this.calculateProgress(pickingData.items);

        this.renderAccordion();
        this.updateGlobalProgress();
        this.playSound('success');
        this.showMessage('item-result', `Đã quét: ${item.name}`, 'success');

        // Call Server to validate/log scan (Optional but good for history)
        // We can background check this OR just trust client until complete.
        // Let's call server async to keep log updated
        this.apiCall('/api/barcode/scan_package', {
            picking_id: targetPickingId,
            barcode: barcode
        }).catch(err => console.error("Log scan failed", err));

        if (input) {
            input.value = '';
            input.focus();
        }

        // 5. Auto-switch to next picking if this one is DONE?
        if (pickingData.progress.isDone) {
            // Find next incomplete
            const allIds = [].concat(...this.soGroups.map(g => g.pickingIds));
            const currentIndex = allIds.indexOf(targetPickingId);
            let nextId = null;

            // Search forward
            for (let i = currentIndex + 1; i < allIds.length; i++) {
                if (!this.pickingDataMap[allIds[i]].progress.isDone) {
                    nextId = allIds[i];
                    break;
                }
            }
            // Search backward (wrap)
            if (!nextId) {
                for (let i = 0; i < currentIndex; i++) {
                    if (!this.pickingDataMap[allIds[i]].progress.isDone) {
                        nextId = allIds[i];
                        break;
                    }
                }
            }

            if (nextId) {
                setTimeout(() => {
                    this.setActivePicking(nextId);
                    // this.showMessage('item-result', 'Đơn đã xong, tự động chuyển tiếp...', 'success');
                }, 500);
            }
        }
    }

    async completeAllDelivery() {
        const pickingIds = Object.keys(this.pickingDataMap).map(id => parseInt(id));
        if (pickingIds.length === 0) return;

        // Store picking IDs for photo step
        this._photoPickingIds = pickingIds;

        // Build so_name→id map cho QR matching (QR trên phiếu = tên sale order)
        this._photoNameToId = {};
        pickingIds.forEach(id => {
            const soName = this.pickingDataMap[id]?.so_name;
            if (soName && soName !== 'Khác') this._photoNameToId[soName] = id;
        });

        // Reset captured photos list
        this._capturedPhotos = [];
        this._photoDetectedPickingId = null;

        // Go to photo capture step
        this._photoBlob = null;
        this._resetPhotoUI();
        this.showDeliverStep('step-photo');
    }

    _resetPhotoUI() {
        this._stopPhotoCamera();
        this._photoBlob = null;
        this._photoDetectedPickingId = null;

        const openSection = document.getElementById('photo-open-section');
        const previewSection = document.getElementById('photo-preview-section');
        const cameraSection = document.getElementById('photo-camera-section');
        const sendBtn = document.getElementById('photo-send-btn');
        const fileInput = document.getElementById('photo-file-input');
        const qrResult = document.getElementById('photo-qr-result');
        const capturedList = document.getElementById('photo-captured-list');

        if (openSection) openSection.style.display = 'block';
        if (previewSection) previewSection.style.display = 'none';
        if (cameraSection) cameraSection.style.display = 'none';
        if (sendBtn) { sendBtn.style.display = 'none'; sendBtn.disabled = false; sendBtn.innerHTML = '<i class="fa fa-paper-plane"></i> Gửi ảnh &amp; Hoàn tất'; }
        if (fileInput) fileInput.value = '';
        if (qrResult) qrResult.innerHTML = '';
        if (capturedList) capturedList.innerHTML = '';
        this.clearMessage('photo-result');

        this._updatePhotoProgress();
        this._renderPendingList();
    }

    async _startPhotoCamera() {
        // Dừng barcode camera nếu đang chạy trước khi mở photo camera
        await this.stopCamera();
        // Đợi một chút để browser release camera hardware
        await new Promise(r => setTimeout(r, 300));
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } },
                audio: false,
            });
            this._photoCameraStream = stream;
            const video = document.getElementById('photo-video');
            if (video) {
                video.srcObject = stream;
                await video.play();
            }
            document.getElementById('photo-camera-section').style.display = 'block';
            document.getElementById('photo-open-section').style.display = 'none';
            // Với nhiều đơn: disable capture cho đến khi QR được nhận diện
            const isMulti = this._photoPickingIds && this._photoPickingIds.length > 1;
            const captureBtn = document.getElementById('photo-capture-btn');
            if (captureBtn) {
                captureBtn.disabled = isMulti;
                captureBtn.innerHTML = isMulti
                    ? '<i class="fa fa-qrcode"></i> Hướng vào mã QR phiếu bàn giao...'
                    : '<i class="fa fa-circle"></i> Chụp ảnh';
            }
            // Bắt đầu scan QR trên camera photo
            this._startPhotoQrLoop();
        } catch (err) {
            console.error('[Photo] Camera error:', err);
            this.showMessage('photo-result', 'Không thể mở camera. Vui lòng chọn ảnh từ thư viện.', 'danger');
        }
    }

    _stopPhotoCamera() {
        // Dừng QR detection loop
        if (this._photoQrLoopTimer) {
            clearTimeout(this._photoQrLoopTimer);
            this._photoQrLoopTimer = null;
        }
        if (this._photoCameraStream) {
            this._photoCameraStream.getTracks().forEach(t => t.stop());
            this._photoCameraStream = null;
        }
        const video = document.getElementById('photo-video');
        if (video) video.srcObject = null;
        const cameraSection = document.getElementById('photo-camera-section');
        if (cameraSection) cameraSection.style.display = 'none';
        const qrOverlay = document.getElementById('photo-qr-overlay');
        if (qrOverlay) qrOverlay.style.display = 'none';
    }

    _capturePhoto() {
        const video = document.getElementById('photo-video');
        const canvas = document.getElementById('photo-canvas');
        if (!video || !canvas) return;

        canvas.width = video.videoWidth || 1280;
        canvas.height = video.videoHeight || 720;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

        // Giữ lại detected picking từ live QR scan trước khi stop camera
        const liveDetectedId = this._photoDetectedPickingId;

        canvas.toBlob(async (blob) => {
            this._photoBlob = blob;
            const url = URL.createObjectURL(blob);
            const img = document.getElementById('photo-preview-img');
            if (img) img.src = url;

            // Dùng live-detected ID, hoặc re-detect từ canvas nếu chưa có
            let detectedId = liveDetectedId;
            if (!detectedId && this._barcodeDetector && this._photoNameToId && Object.keys(this._photoNameToId).length > 0) {
                try {
                    const barcodes = await this._barcodeDetector.detect(canvas);
                    for (const b of barcodes) {
                        const pid = this._photoNameToId[b.rawValue];
                        if (pid !== undefined) { detectedId = pid; break; }
                    }
                } catch (e) { /* ignore */ }
            }
            this._photoDetectedPickingId = detectedId;

            // Hiển kết quả QR
            const qrResult = document.getElementById('photo-qr-result');
            if (qrResult) {
                if (detectedId) {
                    const pickingName = this.pickingDataMap[detectedId]?.info?.name || '';
                    const soName = this.pickingDataMap[detectedId]?.so_name || '';
                    qrResult.innerHTML = `<div style="background:#e8f5e9;color:#2e7d32;padding:6px 12px;border-radius:6px;font-size:13px;font-weight:600;"><i class="fa fa-check-circle"></i> Phiếu: ${pickingName}${soName ? ` (${soName})` : ''}</div>`;
                    if (img) img.style.borderColor = 'var(--success-color)';
                } else if (Object.keys(this._photoNameToId || {}).length > 0) {
                    // Nhiều đơn nhưng không detect được QR — lỗi
                    qrResult.innerHTML = `<div style="background:#ffebee;color:#c62828;padding:6px 12px;border-radius:6px;font-size:13px;"><i class="fa fa-times-circle"></i> Không nhận diện được mã QR. Vui lòng chụp lại.</div>`;
                    if (img) img.style.borderColor = '#e53935';
                } else {
                    qrResult.innerHTML = '';
                    if (img) img.style.borderColor = 'var(--success-color)';
                }
            }

            document.getElementById('photo-preview-section').style.display = 'block';
            this._stopPhotoCamera();
            document.getElementById('photo-open-section').style.display = 'none';
            this._renderCapturedList();
            this._showPhotoPreviewButtons();
        }, 'image/jpeg', 0.85);
    }

    _handlePhotoFile(file) {
        if (!file) return;
        this._photoBlob = file;
        const url = URL.createObjectURL(file);
        const img = document.getElementById('photo-preview-img');
        if (img) {
            img.src = url;
            img.onload = async () => {
                this._photoDetectedPickingId = null;
                // Detect QR từ file ảnh
                if (this._barcodeDetector && this._photoNameToId && Object.keys(this._photoNameToId).length > 0) {
                    try {
                        const barcodes = await this._barcodeDetector.detect(img);
                        for (const b of barcodes) {
                            const pid = this._photoNameToId[b.rawValue];
                            if (pid !== undefined) { this._photoDetectedPickingId = pid; break; }
                        }
                    } catch (e) { /* ignore */ }
                }
                const qrResult = document.getElementById('photo-qr-result');
                if (qrResult) {
                    if (this._photoDetectedPickingId) {
                        const name = this.pickingDataMap[this._photoDetectedPickingId]?.info?.name || '';
                        qrResult.innerHTML = `<div style="background:#e8f5e9;color:#2e7d32;padding:6px 12px;border-radius:6px;font-size:13px;font-weight:600;"><i class="fa fa-check-circle"></i> Nhận diện: ${name}</div>`;
                        if (img) img.style.borderColor = 'var(--success-color)';
                    } else if (Object.keys(this._photoNameToId || {}).length > 0) {
                        qrResult.innerHTML = `<div style="background:#fff3e0;color:#e65100;padding:6px 12px;border-radius:6px;font-size:13px;"><i class="fa fa-exclamation-triangle"></i> Không nhận diện mã QR</div>`;
                        if (img) img.style.borderColor = '#ffa726';
                    }
                }
                this._renderCapturedList();
                this._showPhotoPreviewButtons();
            };
        }
        document.getElementById('photo-preview-section').style.display = 'block';
        document.getElementById('photo-open-section').style.display = 'none';
        this._stopPhotoCamera();
    }

    async sendPhotoAndComplete() {
        // Build danh sách ảnh cần upload
        const photosToUpload = [];
        if (this._capturedPhotos && this._capturedPhotos.length > 0) {
            photosToUpload.push(...this._capturedPhotos);
        } else if (this._photoBlob) {
            photosToUpload.push({ pickingId: null, pickingName: 'Tất cả', blob: this._photoBlob });
        }
        if (photosToUpload.length === 0 || !this._photoPickingIds || this._photoPickingIds.length === 0) return;

        const sendBtn = document.getElementById('photo-send-btn');
        if (sendBtn) {
            sendBtn.disabled = true;
            sendBtn.innerHTML = `<i class="fa fa-spinner fa-spin"></i> Đang gửi ${photosToUpload.length} ảnh...`;
        }
        this.showMessage('photo-result', `Đang tải ${photosToUpload.length} ảnh lên...`, 'warning');

        try {
            for (let i = 0; i < photosToUpload.length; i++) {
                const photo = photosToUpload[i];
                // Nếu biết picking cụ thể thì upload riêng, không biết thì gắn tất cả
                const ids = photo.pickingId ? [photo.pickingId] : this._photoPickingIds;
                const formData = new FormData();
                formData.append('picking_ids', JSON.stringify(ids));
                formData.append('photo', photo.blob, `delivery_photo_${i + 1}.jpg`);
                const uploadRes = await fetch('/api/barcode/upload_delivery_photo', {
                    method: 'POST',
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                    body: formData,
                });
                const uploadJson = await uploadRes.json();
                if (!uploadJson.success) {
                    console.warn(`[Photo] Upload failed for ${photo.pickingName}:`, uploadJson.error);
                }
            }
            this.showMessage('photo-result', 'Ảnh đã gửi! Đang hoàn tất đơn hàng...', 'success');
            await this._doCompleteOut(this._photoPickingIds);
        } catch (e) {
            console.error(e);
            this.showMessage('photo-result', 'Lỗi kết nối khi gửi ảnh', 'danger');
            if (sendBtn) { sendBtn.disabled = false; sendBtn.innerHTML = '<i class="fa fa-paper-plane"></i> Gửi ảnh &amp; Hoàn tất'; }
        }
    }

    async skipPhotoAndComplete() {
        if (!this._photoPickingIds || this._photoPickingIds.length === 0) return;
        this._stopPhotoCamera();
        this.showMessage('photo-result', 'Đang hoàn tất đơn hàng...', 'warning');
        await this._doCompleteOut(this._photoPickingIds);
    }

    // === Hiển thị đúng button sau khi chụp (single vs multi picking) ===
    _showPhotoPreviewButtons() {
        const isSingle = !this._photoPickingIds || this._photoPickingIds.length <= 1;
        const confirmBtn = document.getElementById('photo-confirm-btn');
        const sendBtn = document.getElementById('photo-send-btn');
        if (isSingle) {
            if (confirmBtn) confirmBtn.style.display = 'none';
            if (sendBtn) { sendBtn.style.display = 'flex'; sendBtn.disabled = false; }
        } else {
            // Multi: chỉ cho confirm nếu đã detect được QR
            if (this._photoDetectedPickingId) {
                if (confirmBtn) confirmBtn.style.display = 'flex';
                if (sendBtn) sendBtn.style.display = 'none';
            } else {
                // Không detect QR: không cho lưu, bắt buộc chụp lại
                if (confirmBtn) confirmBtn.style.display = 'none';
                if (sendBtn) sendBtn.style.display = 'none';
                this.showMessage('photo-result', 'Không phát hiện mã QR. Vui lòng chụp lại, đảm bảo mã QR trên phiếu bàn giao rõ ràng.', 'danger');
            }
        }
    }

    // === Lưu ảnh hiện tại vào danh sách, cập nhật tiến độ ===
    _confirmCapturedPhoto() {
        if (!this._photoBlob || !this._photoDetectedPickingId) return;  // Phải có QR detected
        const pickingId = this._photoDetectedPickingId;
        const pickingName = this.pickingDataMap[pickingId]?.info?.name || `#${pickingId}`;

        const existing = this._capturedPhotos.findIndex(p => p.pickingId === pickingId);
        if (existing >= 0) {
            this._capturedPhotos[existing].blob = this._photoBlob;
        } else {
            this._capturedPhotos.push({ pickingId, pickingName, blob: this._photoBlob });
        }

        this._photoBlob = null;
        this._photoDetectedPickingId = null;
        this._updatePhotoProgress();
        this._renderPendingList();

        // Kiểm tra tất cả phiếu đã có ảnh chưa
        const capturedIds = new Set(this._capturedPhotos.map(p => p.pickingId));
        const allCovered = this._photoPickingIds.every(id => capturedIds.has(id));

        document.getElementById('photo-preview-section').style.display = 'none';
        const qrResult = document.getElementById('photo-qr-result');
        if (qrResult) qrResult.innerHTML = '';

        if (allCovered) {
            document.getElementById('photo-open-section').style.display = 'none';
            const sendBtn = document.getElementById('photo-send-btn');
            if (sendBtn) {
                sendBtn.style.display = 'flex';
                sendBtn.disabled = false;
                sendBtn.innerHTML = `<i class="fa fa-paper-plane"></i> Gửi ${this._capturedPhotos.length} ảnh &amp; Hoàn tất`;
            }
            this.showMessage('photo-result', `✓ Đã chụp đủ ${this._capturedPhotos.length} ảnh. Nhấn gửi để hoàn tất.`, 'success');
        } else {
            document.getElementById('photo-open-section').style.display = 'block';
            const remaining = this._photoPickingIds.filter(id => !capturedIds.has(id));
            const nextSoName = this.pickingDataMap[remaining[0]]?.so_name || '';
            this.showMessage('photo-result', `✓ Đã lưu "${pickingName}". Còn ${remaining.length} phiếu${nextSoName ? ` — tiếp theo: QR "${nextSoName}"` : ''}.`, 'success');
        }
    }

    // === Cập nhật thanh tiến độ ===
    _updatePhotoProgress() {
        const total = this._photoPickingIds?.length || 0;
        const capturedIds = new Set((this._capturedPhotos || []).map(p => p.pickingId).filter(Boolean));
        const hasCatchAll = false;  // Không còn catch-all
        const doneCount = capturedIds.size;
        const progressWrap = document.getElementById('photo-progress-wrap');
        const progressText = document.getElementById('photo-progress-text');
        const progressFill = document.getElementById('photo-progress-fill');
        if (total <= 1) {
            if (progressWrap) progressWrap.style.display = 'none';
            return;
        }
        if (progressWrap) progressWrap.style.display = 'block';
        if (progressText) progressText.textContent = `${doneCount}/${total} phiếu`;
        if (progressFill) progressFill.style.width = `${total > 0 ? Math.round(doneCount / total * 100) : 0}%`;
    }

    // === Render danh sách phiếu cần chụp ===
    _renderPendingList() {
        const container = document.getElementById('photo-pending-list');
        if (!container || !this._photoPickingIds || this._photoPickingIds.length <= 1) {
            if (container) container.innerHTML = '';
            return;
        }
        const capturedIds = new Set((this._capturedPhotos || []).map(p => p.pickingId).filter(Boolean));
        const rows = this._photoPickingIds.map(id => {
            const pickingName = this.pickingDataMap[id]?.info?.name || `#${id}`;
            const soName = this.pickingDataMap[id]?.so_name || '';
            const done = capturedIds.has(id);
            return `<div style="display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid #f5f5f5;font-size:13px;">
                <i class="fa ${done ? 'fa-check-circle' : 'fa-circle-o'}" style="color:${done ? '#4caf50' : '#bbb'};font-size:15px;min-width:16px;"></i>
                <div style="flex:1;">
                    <div style="${done ? 'color:#aaa;text-decoration:line-through;' : 'font-weight:600;'}">${pickingName}</div>
                    ${soName ? `<div style="font-size:11px;color:#888;">Đơn hàng: ${soName}</div>` : ''}
                </div>
            </div>`;
        }).join('');
        container.innerHTML = `<div style="font-size:11px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Danh sách phiếu (QR = tên đơn hàng)</div>${rows}`;
    }

    // === Render danh sách ảnh đã lưu (hiển thị trong preview) ===
    _renderCapturedList() {
        const container = document.getElementById('photo-captured-list');
        if (!container) return;
        const photos = this._capturedPhotos || [];
        if (photos.length === 0 || (this._photoPickingIds?.length || 0) <= 1) {
            container.innerHTML = '';
            return;
        }
        const tags = photos.map(p =>
            `<span style="display:inline-flex;align-items:center;gap:4px;background:#e8f5e9;color:#2e7d32;padding:2px 10px;border-radius:12px;margin:2px;font-size:12px;font-weight:600;">
                <i class="fa fa-check"></i> ${p.pickingName}
            </span>`
        ).join('');
        container.innerHTML = `<div style="font-size:11px;color:#888;margin-bottom:4px;">Đã lưu:</div><div>${tags}</div>`;
    }

    // === QR detection loop khi camera photo đang mở ===
    _startPhotoQrLoop() {
        if (!this._barcodeDetector || !this._photoNameToId || Object.keys(this._photoNameToId).length === 0) return;
        const loop = async () => {
            if (!this._photoCameraStream) return;
            const video = document.getElementById('photo-video');
            if (video && video.readyState >= video.HAVE_ENOUGH_DATA) {
                try {
                    const barcodes = await this._barcodeDetector.detect(video);
                    const qrOverlay = document.getElementById('photo-qr-overlay');
                    const qrText = document.getElementById('photo-qr-text');
                    const qrBadge = document.getElementById('photo-qr-badge');
                    const captureBtn = document.getElementById('photo-capture-btn');
                    let matched = null;
                    for (const b of barcodes) {
                        const pid = this._photoNameToId[b.rawValue];
                        if (pid !== undefined) { matched = { soName: b.rawValue, id: pid }; break; }
                    }
                    if (matched) {
                        this._photoDetectedPickingId = matched.id;
                        this._photoQrDetectedAt = Date.now();
                        // Hiển tên phiếu xuất (không phải tên SO) trên overlay
                        const pickingName = this.pickingDataMap[matched.id]?.info?.name || matched.soName;
                        if (qrOverlay) qrOverlay.style.display = 'block';
                        if (qrText) qrText.textContent = `✓ ${pickingName}`;
                        if (qrBadge) qrBadge.style.background = 'rgba(46,125,50,0.9)';
                        // Enable capture button
                        if (captureBtn) {
                            captureBtn.disabled = false;
                            captureBtn.innerHTML = '<i class="fa fa-circle"></i> Chụp ảnh';
                        }
                    } else {
                        // Debounce: chỉ clear detected ID sau 1.5s QR vắng
                        const age = Date.now() - (this._photoQrDetectedAt || 0);
                        if (age > 1500) {
                            this._photoDetectedPickingId = null;
                            if (captureBtn) {
                                captureBtn.disabled = true;
                                captureBtn.innerHTML = '<i class="fa fa-qrcode"></i> Hướng vào mã QR phiếu bàn giao...';
                            }
                        }
                        if (barcodes.length > 0) {
                            if (qrOverlay) qrOverlay.style.display = 'block';
                            if (qrText) qrText.textContent = 'QR không khớp đơn hàng';
                            if (qrBadge) qrBadge.style.background = 'rgba(198,40,40,0.9)';
                        } else if (age > 1500) {
                            if (qrOverlay) qrOverlay.style.display = 'none';
                        }
                    }
                } catch (e) { /* ignore */ }
            }
            this._photoQrLoopTimer = setTimeout(loop, 350);
        };
        this._photoQrLoopTimer = setTimeout(loop, 600);
    }

    async _doCompleteOut(pickingIds) {
        if (!confirm(`Xác nhận hoàn tất ${pickingIds.length} đơn hàng?`)) return;
        try {
            const res = await this.apiCall('/api/barcode/complete_out', { picking_ids: pickingIds });
            if (res.success) {
                document.getElementById('completion-result').textContent = res.message;
                this._stopPhotoCamera();
                this.showDeliverStep('step-complete');
                this.playSound('success');
                this.pickingDataMap = {};
            } else {
                this.showMessage('photo-result', res.error || 'Có lỗi xảy ra', 'danger');
                this.playSound('error');
                const sendBtn = document.getElementById('photo-send-btn');
                if (sendBtn) { sendBtn.disabled = false; sendBtn.innerHTML = '<i class="fa fa-paper-plane"></i> Gửi ảnh & Hoàn tất'; }
            }
        } catch (e) {
            console.error(e);
            this.showMessage('photo-result', 'Lỗi kết nối', 'danger');
            this.playSound('error');
        }
    }

    resetScan() {
        if (confirm('Dữ liệu quét chưa lưu sẽ bị mất. Bạn muốn quét lại từ đầu?')) {
            this.startNewDelivery();
        }
    }

    startNewDelivery() {
        this.pickingDataMap = {};
        this.soGroups = [];
        this.activePickingId = null;
        this.customerName = '';

        this.clearMessage('pick-result');
        this.clearMessage('item-result');

        const info = document.getElementById('so-accordion');
        if (info) info.innerHTML = '';

        document.getElementById('pick-barcode-input').value = '';
        document.getElementById('item-barcode-input').value = '';
        document.getElementById('global-progress-fill').style.width = '0%';
        document.getElementById('global-progress-text').textContent = '0 / 0';
        document.getElementById('customer-info').style.display = 'none';

        this.showDeliverStep('step-scan-pick');
    }

    // Reuse history...
    async showHistory() {
        const modal = document.getElementById('history-modal');
        const content = document.getElementById('history-content');
        if (!modal || !content) return;
        content.innerHTML = 'Đang tải...';
        this.showModal(modal);
        try {
            // Just show history for the first picking or user?
            // If strictly per picking, we might need to select which picking...
            // Ideally history should be global for the session.
            const pid = this.activePickingId || (Object.keys(this.pickingDataMap)[0] ? parseInt(Object.keys(this.pickingDataMap)[0]) : null);

            const res = await this.apiCall('/api/barcode/scan_history', {
                picking_id: pid,
                limit: 50,
            });
            if (res.success && res.history && res.history.length) {
                content.innerHTML = res.history
                    .map(
                        log => `
                    <div style="border-bottom: 1px solid #eee; padding: 8px 0;">
                        <div style="font-size: 12px; color: #888;">${log.scan_time}</div>
                        <div style="font-weight: 600;">${log.barcode}</div>
                        <div style="display: flex; justify-content: space-between; font-size: 13px;">
                            <span class="${log.scan_type}">${log.scan_type}</span>
                            <span class="${log.status}" style="color: ${log.status === 'success' ? 'green' : 'red'}">${log.status}</span>
                        </div>
                        <div style="font-size: 11px; color: #555;">${log.picking_name || ''}</div>
                        ${log.message ? `<div style="font-size: 12px; color: #666;">${log.message}</div>` : ''}
                    </div>`
                    )
                    .join('');
            } else {
                content.innerHTML = 'Chưa có lịch sử quét.';
            }
        } catch (e) {
            console.error(e);
            content.innerHTML = 'Lỗi tải lịch sử.';
        }
    }

    showHelp() {
        const modal = document.getElementById('help-modal');
        if (modal) this.showModal(modal);
    }

    showModal(modal) {
        modal.classList.add('show');
        document.body.style.overflow = 'hidden';
    }

    closeModal(modal) {
        modal.classList.remove('show');
        document.body.style.overflow = '';
        // Refocus input sau khi đóng modal
        this.focusCurrentInput();
    }

    async apiCall(endpoint, data) {
        const res = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
            body: JSON.stringify(data),
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const json = await res.json();

        // Odoo type="json" → { jsonrpc, id, result }
        if (json && typeof json === 'object') {
            if (Object.prototype.hasOwnProperty.call(json, 'result')) {
                return json.result;
            }
            if (Object.prototype.hasOwnProperty.call(json, 'error')) {
                throw new Error(json.error.message || 'JSON-RPC error');
            }
        }

        return json;
    }

    // ========================= RECEIVE TAB =========================

    async loadAvailableToReceive() {
        const container = document.getElementById('receive-available-accordion');
        if (!container) return;
        this.receiveSelectedIds = new Set();
        this.receiveExpandedPickingIds = new Set();
        this.receiveAvailableData = {};
        this.receiveSoGroups = [];
        this.receiveLoadOffset = 0;
        this.receiveLoadTotal = 0;
        this.receiveHasMore = false;
        this.updateReceiveConfirmBar();
        container.innerHTML = `
            <div class="loading-placeholder">
                <i class="fa fa-spinner fa-spin" style="font-size:1.5rem;color:#aaa;"></i>
                <div style="color:#888;margin-top:8px;">Đang tải danh sách phiếu...</div>
            </div>`;
        try {
            const res = await this.apiCall('/api/barcode/get_available_to_receive', { limit: 20, offset: 0 });
            if (res.success) {
                this.receiveSoGroups = res.so_groups || [];
                this.receiveLoadOffset = res.shown || 0;
                this.receiveLoadTotal = res.total || 0;
                this.receiveHasMore = res.has_more || false;
                this.receiveSoGroups.forEach(g => {
                    (g.pickings || []).forEach(p => {
                        this.receiveAvailableData[p.id] = { info: p, items: null };
                    });
                });
                if (this.receiveSoGroups.length === 0) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <i class="fa fa-inbox" style="font-size:3rem;color:#ddd;display:block;margin-bottom:8px;"></i>
                            <div>Không có phiếu nào cần nhận lúc này</div>
                        </div>`;
                } else {
                    this.renderReceiveAccordion();
                }
            } else {
                container.innerHTML = `<div class="empty-state" style="color:var(--danger-color);">Lỗi tải danh sách: ${res.error || ''}</div>`;
            }
        } catch (e) {
            console.error(e);
            container.innerHTML = `<div class="empty-state" style="color:var(--danger-color);">Lỗi kết nối</div>`;
        }
    }

    async loadMoreReceive() {
        const btn = document.getElementById('receive-load-more-btn');
        if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Đang tải...'; }
        try {
            const res = await this.apiCall('/api/barcode/get_available_to_receive', {
                limit: 20,
                offset: this.receiveLoadOffset,
            });
            if (res.success) {
                (res.so_groups || []).forEach(newGroup => {
                    const existing = this.receiveSoGroups.find(g => g.so_name === newGroup.so_name);
                    if (existing) {
                        existing.pickings.push(...(newGroup.pickings || []));
                    } else {
                        this.receiveSoGroups.push(newGroup);
                    }
                });
                (res.so_groups || []).forEach(g => {
                    (g.pickings || []).forEach(p => {
                        if (!this.receiveAvailableData[p.id]) {
                            this.receiveAvailableData[p.id] = { info: p, items: null };
                        }
                    });
                });
                this.receiveLoadOffset += (res.shown || 0);
                this.receiveHasMore = res.has_more || false;
                this.renderReceiveAccordion();
            }
        } catch (e) {
            console.error(e);
            if (btn) { btn.disabled = false; btn.innerHTML = 'Tải thêm'; }
        }
    }

    _showReceivePrompt() {
        this.receiveSoGroups = [];
        this.receiveLoadOffset = 0;
        this.receiveLoadTotal = 0;
        this.receiveHasMore = false;
        this.updateReceiveConfirmBar();
        if (this.receiveSelectedIds.size > 0) {
            // Show "Đã chọn" section even without search results
            this.renderReceiveAccordion();
        } else {
            const container = document.getElementById('receive-available-accordion');
            if (!container) return;
            container.innerHTML = `
                <div class="empty-state">
                    <i class="fa fa-search" style="font-size:2.5rem;color:#ddd;display:block;margin-bottom:10px;"></i>
                    <div style="color:#aaa;">Nhập mã phiếu hoặc đơn hàng để tìm kiếm</div>
                </div>`;
        }
    }

    async searchReceivePickings(query) {
        const input = document.getElementById('receive-barcode-input');
        const container = document.getElementById('receive-available-accordion');
        if (!container) return;

        if (!query) {
            if (input) input.value = '';
            this._showReceivePrompt();
            return;
        }
        if (input) input.value = '';

        container.innerHTML = `
            <div class="loading-placeholder">
                <i class="fa fa-spinner fa-spin" style="font-size:1.5rem;color:#aaa;"></i>
                <div style="color:#888;margin-top:8px;">Đang tìm "${query}"...</div>
            </div>`;
        try {
            const res = await this.apiCall('/api/barcode/get_available_to_receive', { search: query });
            if (res.success) {
                this.receiveSoGroups = res.so_groups || [];
                this.receiveHasMore = false;
                this.receiveLoadTotal = res.total || 0;
                this.receiveSoGroups.forEach(g => {
                    (g.pickings || []).forEach(p => {
                        if (!this.receiveAvailableData[p.id]) {
                            this.receiveAvailableData[p.id] = { info: p, items: null };
                        }
                    });
                });
                if (this.receiveSoGroups.length === 0) {
                    this.renderReceiveAccordion();
                    if (this.receiveSelectedIds.size === 0) {
                        container.querySelector('.receive-search-section-header')?.remove();
                    }
                    // Append "not found" message after the pinned section
                    const notFound = document.createElement('div');
                    notFound.className = 'empty-state';
                    notFound.textContent = `Không tìm thấy phiếu nào chứa "${query}"`;
                    container.appendChild(notFound);
                    this.showMessage('receive-scan-result', `Không tìm thấy phiếu nào chứa "${query}"`, 'warning');
                } else {
                    const autoIds = res.auto_select_ids || [];
                    if (autoIds.length > 0) {
                        autoIds.forEach(id => this.receiveSelectedIds.add(id));
                        this.updateReceiveConfirmBar();
                        this.renderReceiveAccordion(autoIds);
                        this.showMessage('receive-scan-result',
                            `Đã chọn ${autoIds.length} phiếu khớp chính xác`, 'success');
                        this.playSound('success');
                    } else {
                        this.renderReceiveAccordion();
                        this.updateReceiveConfirmBar();
                        this.showMessage('receive-scan-result',
                            `Tìm thấy ${res.total} phiếu chứa "${query}"`, 'info');
                    }
                }
                this.focusCurrentInput();
            } else {
                this.showMessage('receive-scan-result', res.error || 'Lỗi tìm kiếm', 'danger');
                this.playSound('error');
                this.focusCurrentInput();
            }
        } catch (e) {
            console.error(e);
            this.showMessage('receive-scan-result', 'Lỗi kết nối', 'danger');
            this.focusCurrentInput();
        }
    }

    renderReceiveAccordion(highlightIds = null) {
        const container = document.getElementById('receive-available-accordion');
        if (!container) return;
        container.innerHTML = '';

        // Helper: build a picking card element
        const buildPickingEl = (p, extraClass = '') => {
            const isSelected = this.receiveSelectedIds.has(p.id);
            const isExpanded = this.receiveExpandedPickingIds.has(p.id);
            const isHighlighted = !!(highlightIds && highlightIds.includes(p.id));
            const el = document.createElement('div');
            el.className = `receive-picking-item${isSelected ? ' selected' : ''}${isHighlighted ? ' highlighted' : ''}${extraClass ? ' ' + extraClass : ''}`;
            el.id = `receive-p-${p.id}`;
            el.innerHTML = `
                <div class="receive-picking-header">
                    <div class="receive-picking-checkbox${isSelected ? ' checked' : ''}" data-id="${p.id}">
                        <i class="fa fa-check"></i>
                    </div>
                    <div class="receive-picking-info" data-id="${p.id}" style="flex:1;min-width:0;">
                        <div class="receive-picking-name">${p.name}</div>
                        ${p.origin ? `<div class="receive-picking-origin-line"><i class="fa fa-file-alt"></i> ${p.origin}</div>` : ''}
                        <div class="receive-picking-meta">
                            <i class="fa fa-user"></i> ${p.partner_name || ''}
                            ${p.scheduled_date ? `<span style="margin-left:8px;"><i class="fa fa-calendar"></i> ${p.scheduled_date}</span>` : ''}
                            ${p.item_count ? `<span style="margin-left:8px;"><i class="fa fa-boxes"></i> ${p.item_count}</span>` : ''}
                        </div>
                    </div>
                    <button class="receive-expand-btn${isExpanded ? ' expanded' : ''}" data-id="${p.id}" title="Xem chi tiết">
                        <i class="fa fa-chevron-${isExpanded ? 'up' : 'down'}"></i>
                    </button>
                </div>
                <div class="receive-picking-items" id="receive-items-${p.id}" style="${isExpanded ? '' : 'display:none;'}">
                    ${isExpanded && this.receiveAvailableData[p.id]?.items
                        ? this._renderReceiveItemsList(this.receiveAvailableData[p.id].items)
                        : '<div class="loading-placeholder" style="padding:10px;"><i class="fa fa-spinner fa-spin"></i></div>'}
                </div>
            `;
            el.querySelector('.receive-picking-checkbox').addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleReceivePickingSelection(p.id);
            });
            el.querySelector('.receive-picking-info').addEventListener('click', () => {
                this.toggleReceivePickingSelection(p.id);
            });
            el.querySelector('.receive-expand-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleReceivePickingExpand(p.id);
            });
            return el;
        };

        // IDs currently in search results
        const searchResultIds = new Set(
            this.receiveSoGroups.flatMap(g => (g.pickings || []).map(p => p.id))
        );

       

        // --- Section 1: "Kết quả tìm kiếm" --- ALL search results, selected stay visible
        if (this.receiveSoGroups.length > 0) {
            const totalInSearch = this.receiveSoGroups.reduce((s, g) => s + (g.pickings || []).length, 0);
            const searchHeader = document.createElement('div');
            searchHeader.className = 'receive-search-section-header';
            searchHeader.innerHTML = `
                <span><i class="fa fa-search"></i> Kết quả tìm kiếm</span>
                <span class="so-count" style="background:#6c757d;">${totalInSearch} phiếu</span>
            `;
            container.appendChild(searchHeader);

            this.receiveSoGroups.forEach(group => {
                const hasHighlight = highlightIds && group.pickings.some(p => highlightIds.includes(p.id));
                const groupEl = document.createElement('div');
                groupEl.className = 'so-group' + (hasHighlight ? ' expanded' : '');
                groupEl.innerHTML = `
                    <div class="so-group-header">
                        <span class="so-name">${group.so_name}</span>
                        <span class="so-count">${group.pickings.length} phiếu</span>
                    </div>
                    <div class="so-group-content"></div>
                `;
                groupEl.querySelector('.so-group-header').addEventListener('click', () => {
                    groupEl.classList.toggle('expanded');
                });
                const contentDiv = groupEl.querySelector('.so-group-content');
                // Show ALL pickings — selected remain visible with checkmark
                (group.pickings || []).forEach(p => contentDiv.appendChild(buildPickingEl(p)));
                container.appendChild(groupEl);
            });


        }
        // --- Section 2: "Kết quả tìm kiếm" 


        const pinnedIds = Array.from(this.receiveSelectedIds).filter(
            id => !searchResultIds.has(id) && this.receiveAvailableData[id]?.info
        );
        if (pinnedIds.length > 0) {
            const pinnedEl = document.createElement('div');
            pinnedEl.className = 'so-group expanded';
            pinnedEl.innerHTML = `
                <div class="so-group-header so-group-pinned">
                    <span class="so-name"><i class="fa fa-check-circle"></i> Đã chọn</span>
                    <span class="so-count">${pinnedIds.length} phiếu</span>
                </div>
                <div class="so-group-content"></div>
            `;
            const pinnedContent = pinnedEl.querySelector('.so-group-content');
            pinnedIds.forEach(id => pinnedContent.appendChild(
                buildPickingEl(this.receiveAvailableData[id].info, 'pinned-selected')
            ));
            container.appendChild(pinnedEl);
        }
    }

    toggleReceivePickingSelection(pickingId) {
        if (this.receiveSelectedIds.has(pickingId)) {
            this.receiveSelectedIds.delete(pickingId);
        } else {
            this.receiveSelectedIds.add(pickingId);
        }
        this.updateReceiveConfirmBar();
        this.renderReceiveAccordion();
    }

    async toggleReceivePickingExpand(pickingId) {
        const isExpanded = this.receiveExpandedPickingIds.has(pickingId);
        const itemsDiv = document.getElementById(`receive-items-${pickingId}`);
        const btn = document.querySelector(`#receive-p-${pickingId} .receive-expand-btn`);

        if (isExpanded) {
            this.receiveExpandedPickingIds.delete(pickingId);
            if (itemsDiv) itemsDiv.style.display = 'none';
            if (btn) { btn.classList.remove('expanded'); btn.innerHTML = '<i class="fa fa-chevron-down"></i>'; }
        } else {
            this.receiveExpandedPickingIds.add(pickingId);
            if (btn) { btn.classList.add('expanded'); btn.innerHTML = '<i class="fa fa-chevron-up"></i>'; }
            if (itemsDiv) {
                itemsDiv.style.display = 'block';
                if (!this.receiveAvailableData[pickingId]?.items) {
                    itemsDiv.innerHTML = '<div class="loading-placeholder" style="padding:10px;"><i class="fa fa-spinner fa-spin"></i> Đang tải...</div>';
                    try {
                        const res = await this.apiCall('/api/barcode/get_multiple_outs', { picking_ids: [pickingId] });
                        if (res.success && res.data && res.data[0]) {
                            const items = res.data[0].items || [];
                            this.receiveAvailableData[pickingId].items = items;
                            itemsDiv.innerHTML = this._renderReceiveItemsList(items);
                        }
                    } catch (e) {
                        itemsDiv.innerHTML = '<div style="color:var(--danger-color);padding:10px;">Lỗi tải danh sách</div>';
                    }
                } else {
                    itemsDiv.innerHTML = this._renderReceiveItemsList(this.receiveAvailableData[pickingId].items);
                }
            }
        }
    }

    _renderReceiveItemsList(items) {
        if (!items || items.length === 0) {
            return '<div style="padding:10px;color:#888;text-align:center;">Không có mặt hàng</div>';
        }
        return items.map(i => {
            const childrenHtml = (i.type === 'package' && i.children && i.children.length)
                ? `<div class="receive-item-children">${i.children.map(c => `
                    <div class="receive-item-child">
                        <i class="fa fa-cube" style="color:#aaa;font-size:0.75rem;"></i>
                        <span class="receive-item-child-name">${c.name}</span>
                        ${c.barcode ? `<span class="receive-item-child-barcode">${c.barcode}</span>` : ''}
                        <span class="receive-item-child-qty">x${c.qty}</span>
                    </div>`).join('')}</div>`
                : '';
            return `
            <div class="receive-item-row">
                <div class="receive-item-icon">
                    ${i.type === 'package' ? '<i class="fa fa-box"></i>' : '<i class="fa fa-cube"></i>'}
                </div>
                <div class="receive-item-info">
                    <div class="receive-item-name">${i.name || ''}</div>
                    <div class="receive-item-meta">
                        ${i.barcode && i.type !== 'package' ? `<span><i class="fa fa-barcode"></i> ${i.barcode}</span>` : ''}
                        <span style="margin-left:${i.type !== 'package' ? '6' : '0'}px;">SL: <b>${i.qty || 0}</b></span>
                    </div>
                    ${childrenHtml}
                </div>
            </div>`;
        }).join('');
    }

    updateReceiveConfirmBar() {
        const count = this.receiveSelectedIds.size;
        const bar = document.getElementById('receive-confirm-bar');
        if (!bar) return;
        bar.style.display = count > 0 ? 'block' : 'none';
        if (count === 0) return;
        bar.innerHTML = `
            <button id="confirm-receive-selected-btn" class="btn btn-success">
                <i class="fa fa-check-circle"></i> X\u00e1c nh\u1eadn nh\u1eadn ${count} phi\u1ebfu
            </button>
        `;
        bar.querySelector('#confirm-receive-selected-btn')?.addEventListener('click', () => this.confirmReceiveSelected());
    }

    async confirmReceiveSelected() {
        if (this.receiveSelectedIds.size === 0) {
            this.showMessage('receive-scan-result', 'Vui lòng chọn ít nhất một phiếu', 'danger');
            return;
        }
        this.receivePickingIds = Array.from(this.receiveSelectedIds);
        if (this.settings.receive_require_detail_scan) {
            this.showMessage('receive-scan-result', 'Đang tải chi tiết phiếu...', 'warning');
            try {
                const detailRes = await this.apiCall('/api/barcode/get_multiple_outs', { picking_ids: this.receivePickingIds });
                if (detailRes.success) {
                    this.receiveItems = [];
                    detailRes.data.forEach(d => {
                        (d.items || []).forEach(i => {
                            const autoSkip =
                                (i.type === 'package' && this.settings.receive_skip_package_scan) ||
                                (i.type === 'product' && this.settings.receive_skip_product_scan);
                            this.receiveItems.push({ ...i, scanned_qty: autoSkip ? (i.qty || 0) : 0 });
                        });
                    });
                    const nameEl = document.getElementById('receive-customer-name');
                    const infoEl = document.getElementById('receive-customer-info');
                    if (nameEl) nameEl.textContent = `${this.receivePickingIds.length} phiếu`;
                    if (infoEl) infoEl.style.display = 'block';
                    this.renderReceiveItems();
                    this.updateReceiveProgress();
                    this.showReceiveStep('receive-step-detail');
                } else {
                    this.showMessage('receive-scan-result', detailRes.error || 'Lỗi tải chi tiết phiếu', 'danger');
                }
            } catch (e) {
                this.showMessage('receive-scan-result', 'Lỗi kết nối', 'danger');
            }
        } else {
            await this.doConfirmReceive();
        }
    }

    async scanReceivePicking() {
        const input = document.getElementById('receive-barcode-input');
        const barcode = (input?.value || '').trim();
        if (!barcode) {
            this.showMessage('receive-scan-result', 'Vui lòng nhập mã phiếu', 'danger');
            return;
        }
        if (input) input.value = '';
        this.showMessage('receive-scan-result', 'Đang tìm phiếu...', 'warning');
        try {
            const res = await this.apiCall('/api/barcode/scan_pick_receive', { barcode });
            if (res.success) {
                const relatedIds = res.related_ids || [];
                if (relatedIds.length === 0) {
                    this.showMessage('receive-scan-result', 'Không tìm thấy phiếu chưa nhận', 'warning');
                    return;
                }
                // Auto-select found pickings
                relatedIds.forEach(id => this.receiveSelectedIds.add(id));
                this.renderReceiveAccordion(relatedIds);
                this.updateReceiveConfirmBar();
                this.showMessage('receive-scan-result', res.message || `Đã chọn ${relatedIds.length} phiếu`, 'success');
                this.playSound('success');
                setTimeout(() => {
                    const el = document.getElementById(`receive-p-${relatedIds[0]}`);
                    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }, 200);
            } else {
                this.showMessage('receive-scan-result', res.error || 'Không tìm thấy', 'danger');
                this.playSound('error');
                this.focusCurrentInput();
            }
        } catch (e) {
            console.error(e);
            this.showMessage('receive-scan-result', 'Lỗi kết nối server', 'danger');
            this.playSound('error');
            this.focusCurrentInput();
        }
    }

    async scanReceiveDetail() {
        const input = document.getElementById('receive-detail-barcode-input');
        const barcode = (input?.value || '').trim();
        if (!barcode || !this.receiveItems) return;

        const item = this.receiveItems.find(i => i.barcode === barcode && (i.scanned_qty || 0) < (i.qty || 0));
        if (!item) {
            const full = this.receiveItems.find(i => i.barcode === barcode);
            this.showMessage('receive-detail-result', full ? 'Sản phẩm đã đủ số lượng!' : `Không tìm thấy: ${barcode}`, full ? 'warning' : 'danger');
            this.playSound('error');
            if (input) { input.value = ''; input.focus(); }
            return;
        }
        item.type === 'package' ? item.scanned_qty = item.qty : item.scanned_qty++;
        this.renderReceiveItems();
        this.updateReceiveProgress();
        this.playSound('success');
        this.showMessage('receive-detail-result', `✓ ${item.name}`, 'success');
        if (input) { input.value = ''; input.focus(); }
    }

    renderReceiveItems() {
        const container = document.getElementById('receive-so-accordion');
        if (!container || !this.receiveItems) return;
        container.innerHTML = '';
        this.receiveItems.forEach(item => {
            const isFull = (item.scanned_qty || 0) >= (item.qty || 0);
            const div = document.createElement('div');
            div.className = `item-card ${isFull ? 'scanned' : ''}`;
            div.innerHTML = `
                <div class="item-info">
                    <div class="item-name">${item.name || ''}</div>
                    <div class="item-details" style="display:flex;gap:10px;font-size:0.8rem;color:#666;">
                        <span><i class="fa fa-barcode"></i> ${item.barcode || ''}</span>
                        <span>SL: <b>${item.scanned_qty}/${item.qty}</b></span>
                    </div>
                </div>
                <div class="item-status-icon">
                    ${isFull ? '<i class="fa fa-check-circle" style="color:var(--success-color)"></i>' : (item.type === 'package' ? '<i class="fa fa-box"></i>' : '<i class="fa fa-cube"></i>')}
                </div>
            `;
            container.appendChild(div);
        });
    }

    updateReceiveProgress() {
        if (!this.receiveItems) return;
        const total = this.receiveItems.reduce((s, i) => s + (i.qty || 0), 0);
        const scanned = this.receiveItems.reduce((s, i) => s + (i.scanned_qty || 0), 0);
        const percent = total ? (scanned / total * 100) : 0;
        const text = document.getElementById('receive-progress-text');
        const fill = document.getElementById('receive-progress-fill');
        const btn = document.getElementById('confirm-receive-btn');
        if (text) text.textContent = `${scanned} / ${total}`;
        if (fill) fill.style.width = `${percent}%`;
        if (btn) btn.style.display = (scanned >= total && total > 0) ? 'block' : 'none';
    }

    async confirmReceive() { await this.doConfirmReceive(); }

    async doConfirmReceive() {
        if (!this.receivePickingIds || this.receivePickingIds.length === 0) return;
        this.showMessage('receive-scan-result', 'Đang xác nhận nhận hàng...', 'warning');
        this.showMessage('receive-detail-result', 'Đang xác nhận nhận hàng...', 'warning');
        try {
            const res = await this.apiCall('/api/barcode/receive_pickings', { picking_ids: this.receivePickingIds });
            if (res.success) {
                this.playSound('success');
                this.showMessage('receive-scan-result', res.message || 'Đã nhận hàng thành công!', 'success');
                this.receivePickingIds = [];
                this.receiveItems = null;
                this.receiveSelectedIds = new Set();
                this.receiveExpandedPickingIds = new Set();
                this.updateReceiveConfirmBar();
                this.showReceiveStep('receive-step-scan');
                const inp = document.getElementById('receive-barcode-input');
                if (inp) inp.value = '';
                // Refresh available list and return list
                this._showReceivePrompt();
                this.loadReturnList();
            } else {
                const errMsg = res.error || 'Lỗi xác nhận nhận hàng';
                this.showMessage('receive-detail-result', errMsg, 'danger');
                this.showMessage('receive-scan-result', errMsg, 'danger');
                this.playSound('error');
            }
        } catch (e) {
            console.error(e);
            this.showMessage('receive-detail-result', 'Lỗi kết nối server', 'danger');
            this.playSound('error');
        }
    }

    // ========================= RETURN TAB =========================

    async loadReturnList() {
        const container = document.getElementById('return-picking-list');
        if (!container) return;
        container.innerHTML = '<div style="text-align:center;padding:20px;color:#888;"><i class="fa fa-spinner fa-spin"></i> Đang tải...</div>';
        try {
            const res = await this.apiCall('/api/barcode/get_my_received', {});
            if (res.success && res.pickings && res.pickings.length > 0) {
                this.returnPickings = res.pickings;
                this.returnSelectedIds = new Set();
                this.renderReturnPickingList(res.pickings);
            } else {
                this.returnPickings = [];
                container.innerHTML = '<div style="text-align:center;padding:20px;color:#888;"><i class="fa fa-inbox" style="font-size:2rem;display:block;margin-bottom:8px;"></i>Chưa có phiếu nào đã nhận.</div>';
                const actions = document.getElementById('return-actions');
                if (actions) actions.style.display = 'none';
            }
        } catch (e) {
            container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--danger-color);">Lỗi tải danh sách.</div>';
        }
    }

    renderReturnPickingList(pickings) {
        const container = document.getElementById('return-picking-list');
        if (!container) return;
        container.innerHTML = '';
        this.returnSelectedIds = new Set();
        this.returnExpandedIds = new Set();
        this.returnItemCache = {};
        const actions = document.getElementById('return-actions');
        if (actions) actions.style.display = 'none';
        this._updateReturnSelectAllBtn();

        pickings.forEach(p => {
            const card = document.createElement('div');
            card.className = 'return-picking-card';
            card.id = `return-pc-${p.id}`;
            card.dataset.id = p.id;
            card.innerHTML = `
                <div class="return-card-header">
                    <div style="flex:1;min-width:0;">
                        <div style="font-weight:700;font-size:1rem;color:var(--primary-color);">${p.name}</div>
                        ${p.origin ? `<div style="font-size:0.78rem;color:var(--text-muted);margin-top:1px;"><i class="fa fa-file-alt"></i> ${p.origin}</div>` : ''}
                        <div style="font-size:0.82rem;color:#888;margin-top:3px;">
                            <i class="fa fa-user"></i> ${p.partner_name || ''}
                            ${p.receive_time ? ` &nbsp;·&nbsp; <i class="fa fa-clock"></i> ${p.receive_time}` : ''}
                            ${p.item_count ? ` &nbsp;·&nbsp; <i class="fa fa-box"></i> ${p.item_count} kiện` : ''}
                        </div>
                    </div>
                    <button class="return-expand-btn" data-id="${p.id}" title="Xem hàng hóa">
                        <i class="fa fa-chevron-down"></i>
                    </button>
                    <div class="check-circle"><i class="fa fa-check"></i></div>
                </div>
                <div class="return-card-items" id="return-items-${p.id}" style="display:none;"></div>
            `;

            // Header click → toggle selection
            card.querySelector('.return-card-header').addEventListener('click', (e) => {
                const id = p.id;
                if (this.returnSelectedIds.has(id)) {
                    this.returnSelectedIds.delete(id);
                    card.classList.remove('selected');
                } else {
                    this.returnSelectedIds.add(id);
                    card.classList.add('selected');
                }
                if (actions) actions.style.display = this.returnSelectedIds.size > 0 ? 'block' : 'none';
                this._updateReturnSelectAllBtn();
            });

            // Expand button → show items (stopPropagation prevents selection)
            card.querySelector('.return-expand-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleReturnPickingExpand(p.id);
            });

            container.appendChild(card);
        });
    }

    toggleReturnSelectAll() {
        if (!this.returnPickings || this.returnPickings.length === 0) return;
        const actions = document.getElementById('return-actions');
        const allSelected = this.returnSelectedIds.size === this.returnPickings.length;

        if (allSelected) {
            // Deselect all
            this.returnSelectedIds = new Set();
            document.querySelectorAll('.return-picking-card').forEach(c => c.classList.remove('selected'));
        } else {
            // Select all
            this.returnPickings.forEach(p => this.returnSelectedIds.add(p.id));
            document.querySelectorAll('.return-picking-card').forEach(c => c.classList.add('selected'));
        }
        if (actions) actions.style.display = this.returnSelectedIds.size > 0 ? 'block' : 'none';
        this._updateReturnSelectAllBtn();
    }

    async scanReturnPicking() {
        const input = document.getElementById('return-scan-input');
        const barcode = (input?.value || '').trim();
        if (!barcode || !this.returnPickings) return;
        if (input) { input.value = ''; input.focus(); input.select(); }

        // 1. Tìm trực tiếp trong danh sách đã tải (theo tên OUT hoặc SO)
        const match = this.returnPickings.find(p =>
            p.name === barcode || (p.origin && p.origin === barcode)
        );
        if (match) {
            this._selectReturnPicking(match);
            return;
        }

        // 2. Fallback: quét mã PICK → gọi API tìm phiếu OUT liên quan
        this.showMessage('return-result', 'Đang tìm phiếu...', 'warning');
        try {
            const res = await this.apiCall('/api/barcode/scan_pick_return', { barcode });
            if (res.success && res.related_ids && res.related_ids.length > 0) {
                let selectedCount = 0;
                res.related_ids.forEach(id => {
                    const p = this.returnPickings.find(rp => rp.id === id);
                    if (p) {
                        this._selectReturnPicking(p);
                        selectedCount++;
                    }
                });
                if (selectedCount > 0) {
                    this.showMessage('return-result', res.message || `Đã chọn ${selectedCount} phiếu`, 'success');
                    this.playSound('success');
                } else {
                    this.showMessage('return-result', 'Phiếu liên quan không nằm trong danh sách trả hàng', 'warning');
                    this.playSound('error');
                }
            } else {
                this.showMessage('return-result', res.error || `Không tìm thấy phiếu "${barcode}"`, 'danger');
                this.playSound('error');
            }
        } catch (e) {
            console.error(e);
            this.showMessage('return-result', `Không tìm thấy phiếu "${barcode}"`, 'danger');
            this.playSound('error');
        }
        this.focusCurrentInput();
    }

    _selectReturnPicking(p) {
        const card = document.getElementById(`return-pc-${p.id}`);
        if (card && !this.returnSelectedIds.has(p.id)) {
            this.returnSelectedIds.add(p.id);
            card.classList.add('selected');
            const actions = document.getElementById('return-actions');
            if (actions) actions.style.display = 'block';
            this._updateReturnSelectAllBtn();
        }
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        this.showMessage('return-result', `Đã chọn ${p.name}`, 'success');
        this.playSound('success');
    }

    _updateReturnSelectAllBtn() {
        const btn = document.getElementById('return-select-all-btn');
        if (!btn) return;
        const allSelected = this.returnPickings && this.returnPickings.length > 0
            && this.returnSelectedIds.size === this.returnPickings.length;
        btn.innerHTML = allSelected
            ? '<i class="fa fa-times"></i> Bỏ chọn tất cả'
            : '<i class="fa fa-check-double"></i> Chọn tất cả';
    }

    async toggleReturnPickingExpand(pickingId) {
        const isExpanded = this.returnExpandedIds.has(pickingId);
        const itemsDiv = document.getElementById(`return-items-${pickingId}`);
        const btn = document.querySelector(`#return-pc-${pickingId} .return-expand-btn`);

        if (isExpanded) {
            this.returnExpandedIds.delete(pickingId);
            if (itemsDiv) itemsDiv.style.display = 'none';
            if (btn) btn.innerHTML = '<i class="fa fa-chevron-down"></i>';
        } else {
            this.returnExpandedIds.add(pickingId);
            if (btn) btn.innerHTML = '<i class="fa fa-chevron-up"></i>';
            if (itemsDiv) {
                itemsDiv.style.display = 'block';
                if (this.returnItemCache[pickingId]) {
                    itemsDiv.innerHTML = this._renderReceiveItemsList(this.returnItemCache[pickingId]);
                } else {
                    itemsDiv.innerHTML = '<div class="loading-placeholder" style="padding:10px;"><i class="fa fa-spinner fa-spin"></i> Đang tải...</div>';
                    try {
                        const res = await this.apiCall('/api/barcode/get_multiple_outs', { picking_ids: [pickingId] });
                        if (res.success && res.data && res.data[0]) {
                            const items = res.data[0].items || [];
                            this.returnItemCache[pickingId] = items;
                            itemsDiv.innerHTML = this._renderReceiveItemsList(items);
                        } else {
                            itemsDiv.innerHTML = '<div style="padding:10px;color:#888;">Không có dữ liệu</div>';
                        }
                    } catch (e) {
                        itemsDiv.innerHTML = '<div style="padding:10px;color:var(--danger-color);">Lỗi tải</div>';
                    }
                }
            }
        }
    }

    async confirmReturn() {
        if (this.returnSelectedIds.size === 0) {
            this.showMessage('return-result', 'Vui lòng chọn ít nhất một phiếu để trả', 'danger');
            return;
        }
        const reason = document.getElementById('return-reason-input')?.value?.trim() || '';
        if (!reason) {
            this.showMessage('return-result', 'Vui lòng nhập lý do trả hàng', 'danger');
            document.getElementById('return-reason-input')?.focus();
            return;
        }
        const selectedArray = Array.from(this.returnSelectedIds);

        if (this.settings.return_require_detail_scan) {
            this.returnPickingId = selectedArray.length === 1 ? selectedArray[0] : selectedArray;
            this.returnReason = reason;
            try {
                const res = await this.apiCall('/api/barcode/get_multiple_outs', { picking_ids: selectedArray });
                if (res.success) {
                    this.returnDetailItems = [];
                    res.data.forEach(d => {
                        (d.items || []).forEach(i => {
                            const autoSkip =
                                (i.type === 'package' && this.settings.return_skip_package_scan) ||
                                (i.type === 'product' && this.settings.return_skip_product_scan);
                            this.returnDetailItems.push({ ...i, scanned_qty: autoSkip ? (i.qty || 0) : 0 });
                        });
                    });
                    this.renderReturnDetailItems();
                    this.updateReturnProgress();
                    this.showReturnStep('return-step-detail');
                } else {
                    this.showMessage('return-result', res.error || 'Lỗi tải chi tiết phiếu', 'danger');
                }
            } catch (e) {
                this.showMessage('return-result', 'Lỗi kết nối server', 'danger');
            }
        } else {
            await this.doConfirmReturn(selectedArray, reason);
        }
    }

    async scanReturnDetail() {
        const input = document.getElementById('return-detail-barcode-input');
        const barcode = (input?.value || '').trim();
        if (!barcode || !this.returnDetailItems) return;

        const item = this.returnDetailItems.find(i => i.barcode === barcode && (i.scanned_qty || 0) < (i.qty || 0));
        if (!item) {
            const full = this.returnDetailItems.find(i => i.barcode === barcode);
            this.showMessage('return-detail-result', full ? 'Đã đủ số lượng!' : `Không tìm thấy: ${barcode}`, full ? 'warning' : 'danger');
            this.playSound('error');
            if (input) { input.value = ''; input.focus(); }
            return;
        }
        item.type === 'package' ? item.scanned_qty = item.qty : item.scanned_qty++;
        this.renderReturnDetailItems();
        this.updateReturnProgress();
        this.playSound('success');
        this.showMessage('return-detail-result', `✓ ${item.name}`, 'success');
        if (input) { input.value = ''; input.focus(); }
    }

    renderReturnDetailItems() {
        const container = document.getElementById('return-so-accordion');
        if (!container || !this.returnDetailItems) return;
        container.innerHTML = '';
        this.returnDetailItems.forEach(item => {
            const isFull = (item.scanned_qty || 0) >= (item.qty || 0);
            const div = document.createElement('div');
            div.className = `item-card ${isFull ? 'scanned' : ''}`;
            div.innerHTML = `
                <div class="item-info">
                    <div class="item-name">${item.name || ''}</div>
                    <div class="item-details" style="display:flex;gap:10px;font-size:0.8rem;color:#666;">
                        <span><i class="fa fa-barcode"></i> ${item.barcode || ''}</span>
                        <span>SL: <b>${item.scanned_qty}/${item.qty}</b></span>
                    </div>
                </div>
                <div class="item-status-icon">
                    ${isFull ? '<i class="fa fa-check-circle" style="color:var(--success-color)"></i>' : (item.type === 'package' ? '<i class="fa fa-box"></i>' : '<i class="fa fa-cube"></i>')}
                </div>
            `;
            container.appendChild(div);
        });
    }

    updateReturnProgress() {
        if (!this.returnDetailItems) return;
        const total = this.returnDetailItems.reduce((s, i) => s + (i.qty || 0), 0);
        const scanned = this.returnDetailItems.reduce((s, i) => s + (i.scanned_qty || 0), 0);
        const percent = total ? (scanned / total * 100) : 0;
        const text = document.getElementById('return-progress-text');
        const fill = document.getElementById('return-progress-fill');
        const btn = document.getElementById('confirm-return-detail-btn');
        if (text) text.textContent = `${scanned} / ${total}`;
        if (fill) fill.style.width = `${percent}%`;
        if (btn) btn.style.display = (scanned >= total && total > 0) ? 'block' : 'none';
    }

    async confirmReturnDetail() {
        const ids = Array.isArray(this.returnPickingId) ? this.returnPickingId : [this.returnPickingId];
        await this.doConfirmReturn(ids, this.returnReason);
    }

    async doConfirmReturn(pickingIds, reason) {
        this.showMessage('return-result', 'Đang xử lý trả hàng...', 'warning');
        this.showMessage('return-detail-result', 'Đang xử lý trả hàng...', 'warning');
        try {
            const res = await this.apiCall('/api/barcode/return_pickings', { picking_ids: pickingIds, reason });
            if (res.success) {
                this.playSound('success');
                this.showMessage('return-result', res.message || 'Đã trả hàng thành công!', 'success');
                this.returnSelectedIds = new Set();
                this.returnPickingId = null;
                this.returnDetailItems = null;
                this.returnReason = '';
                const ri = document.getElementById('return-reason-input');
                if (ri) ri.value = '';
                this.showReturnStep('return-step-list');
                await this.loadReturnList();
            } else {
                const errMsg = res.error || 'Lỗi xác nhận trả hàng';
                this.showMessage('return-detail-result', errMsg, 'danger');
                this.showMessage('return-result', errMsg, 'danger');
                this.playSound('error');
            }
        } catch (e) {
            console.error(e);
            this.showMessage('return-detail-result', 'Lỗi kết nối server', 'danger');
            this.playSound('error');
        }
    }

    // ========================= DELIVERED TAB =========================

    async loadDeliveredList(dateFilter) {
        const container = document.getElementById('delivered-list');
        if (!container) return;
        container.innerHTML = '<div style="text-align:center;padding:20px;color:#888;"><i class="fa fa-spinner fa-spin"></i> Đang tải...</div>';
        try {
            const params = {};
            if (dateFilter) params.date_filter = dateFilter;
            const res = await this.apiCall('/api/barcode/get_delivered', params);
            if (res.success && res.pickings && res.pickings.length > 0) {
                this.renderDeliveredList(res.pickings);
            } else {
                container.innerHTML = '<div style="text-align:center;padding:20px;color:#888;"><i class="fa fa-clipboard-check" style="font-size:2rem;display:block;margin-bottom:8px;"></i>Chưa có đơn hàng nào đã giao.</div>';
            }
        } catch (e) {
            container.innerHTML = '<div style="text-align:center;padding:20px;color:var(--danger-color);">Lỗi tải danh sách.</div>';
        }
    }

    renderDeliveredList(pickings) {
        const container = document.getElementById('delivered-list');
        if (!container) return;
        container.innerHTML = '';

        pickings.forEach(p => {
            const card = document.createElement('div');
            card.className = 'delivered-card';
            card.innerHTML = `
                <div style="display:flex;align-items:flex-start;gap:10px;">
                    <div style="flex-shrink:0;width:36px;height:36px;border-radius:50%;background:#e8f5e9;display:flex;align-items:center;justify-content:center;">
                        <i class="fa fa-check" style="color:#43a047;font-size:1rem;"></i>
                    </div>
                    <div style="flex:1;min-width:0;">
                        <div style="font-weight:700;font-size:0.95rem;color:var(--primary-color);">${p.name}</div>
                        ${p.origin ? `<div style="font-size:0.78rem;color:var(--text-muted);margin-top:1px;"><i class="fa fa-file-alt"></i> ${p.origin}</div>` : ''}
                        <div style="font-size:0.82rem;color:#888;margin-top:3px;">
                            ${p.partner_name ? `<i class="fa fa-user"></i> ${p.partner_name}` : ''}
                            ${p.date_done ? ` &nbsp;·&nbsp; <i class="fa fa-clock"></i> ${p.date_done}` : ''}
                        </div>
                    </div>
                </div>
            `;
            container.appendChild(card);
        });
    }
}

// Auto-init
document.addEventListener('DOMContentLoaded', () => {
    if (document.querySelector('.shipper-container')) {
        window.barcodeShipper = new BarcodeShipper();
    }
});

// Service Worker (Optional)
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker
            .register('/hlv_barcode_shipper/static/src/js/sw.js')
            .catch(err => console.warn('SW failed:', err));
    });
}