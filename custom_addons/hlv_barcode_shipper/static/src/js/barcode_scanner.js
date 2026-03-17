// hlv_barcode_shipper/static/src/js/barcode_scanner.js
/**
 * HLV Barcode Shipper JavaScript
 * Supports 3 tabs: Nhận hàng / Giao hàng / Trả hàng
 * Supports hardware barcode scanner (keyboard Enter) + camera (html5-qrcode)
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
        this.html5QrCode = null;
        this.isCameraRunning = false;
        this.currentCameraSection = null;
        this.currentCameraMode = null;

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

        // === RECEIVE TAB ===
        document.getElementById('receive-scan-btn')?.addEventListener('click', () => {
            const q = document.getElementById('receive-barcode-input')?.value?.trim() || '';
            this.searchReceivePickings(q);
        });
        document.getElementById('btn-close-camera-receive')?.addEventListener('click', () => this.stopCamera());
        document.getElementById('btn-refresh-receive')?.addEventListener('click', () => this.loadAvailableToReceive());
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
            if (input) input.focus();
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

    async startCamera(sectionId, readerId, mode) {
        if (this.isCameraRunning && this.currentCameraSection === sectionId) return;
        if (this.isCameraRunning) await this.stopCamera();

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
        };
        const btnId = btnMap[mode];
        if (btnId) {
            const btn = document.getElementById(btnId);
            if (btn) btn.style.display = 'none';
        }

        this.html5QrCode = new Html5Qrcode(readerId);
        const config = { fps: 20, qrbox: { width: 280, height: 150 } };

        try {
            await this.html5QrCode.start(
                { facingMode: "environment" },
                config,
                (decodedText) => this.onScanSuccess(decodedText, mode),
                () => {}
            );
            this.isCameraRunning = true;
        } catch (err) {
            console.error("Error starting camera:", err);
            if (btnId) {
                const btn = document.getElementById(btnId);
                if (btn) btn.style.display = 'block';
            }
            if (section) section.classList.remove('active');
        }
    }

    async stopCamera() {
        if (this.html5QrCode && this.isCameraRunning) {
            try {
                await this.html5QrCode.stop();
                this.html5QrCode.clear();
            } catch (e) {
                console.error("Failed to stop camera", e);
            }
        }
        this.isCameraRunning = false;
        this.currentCameraSection = null;
        this.currentCameraMode = null;

        document.querySelectorAll('.camera-section').forEach(el => el.classList.remove('active'));
        ['btn-open-camera-pick', 'btn-open-camera-item', 'btn-open-camera-receive',
            'btn-open-camera-receive-detail', 'btn-open-camera-return-detail'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) btn.style.display = 'block';
        });
    }

    onScanSuccess(decodedText, mode) {
        if (mode === 'pick') {
            const input = document.getElementById('pick-barcode-input');
            if (input) { input.value = decodedText; this.scanPickOrder(); this.stopCamera(); }
        } else if (mode === 'item') {
            const input = document.getElementById('item-barcode-input');
            if (input) {
                input.value = decodedText;
                this.scanItem();
                this.html5QrCode?.pause();
                setTimeout(() => this.html5QrCode?.resume(), 500);
            }
        } else if (mode === 'receive') {
            const input = document.getElementById('receive-barcode-input');
            if (input) input.value = decodedText;
            this.stopCamera();
            this.searchReceivePickings(decodedText);
        } else if (mode === 'receive-detail') {
            const input = document.getElementById('receive-detail-barcode-input');
            if (input) {
                input.value = decodedText;
                this.scanReceiveDetail();
                this.html5QrCode?.pause();
                setTimeout(() => this.html5QrCode?.resume(), 500);
            }
        } else if (mode === 'return-detail') {
            const input = document.getElementById('return-detail-barcode-input');
            if (input) {
                input.value = decodedText;
                this.scanReturnDetail();
                this.html5QrCode?.pause();
                setTimeout(() => this.html5QrCode?.resume(), 500);
            }
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
            }
        } catch (e) {
            console.error(e);
            this.showMessage('pick-result', 'Lỗi kết nối, vui lòng thử lại.', 'danger');
            this.playSound('error');
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

        if (!confirm(`Bạn có chắc muốn hoàn tất ${pickingIds.length} đơn hàng?`)) return;

        this.showMessage('item-result', 'Đang xử lý hoàn tất...', 'warning');
        try {
            const res = await this.apiCall('/api/barcode/complete_out', {
                picking_ids: pickingIds
            });

            if (res.success) {
                // Show success screen
                document.getElementById('completion-result').textContent = res.message;
                this.showDeliverStep('step-complete');
                this.playSound('success');
                this.pickingDataMap = {}; // clear
            } else {
                this.showMessage('item-result', res.error || 'Có lỗi xảy ra', 'danger');
                this.playSound('error');
            }
        } catch (e) {
            console.error(e);
            this.showMessage('item-result', 'Lỗi kết nối', 'danger');
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
        const container = document.getElementById('receive-available-accordion');
        if (!container) return;
        // Keep receiveSelectedIds and receiveAvailableData so selections persist
        // across multiple searches — only clear the paginated result groups
        this.receiveSoGroups = [];
        this.receiveLoadOffset = 0;
        this.receiveLoadTotal = 0;
        this.receiveHasMore = false;
        this.updateReceiveConfirmBar();
        container.innerHTML = `
            <div class="empty-state">
                <i class="fa fa-search" style="font-size:2.5rem;color:#ddd;display:block;margin-bottom:10px;"></i>
                <div style="color:#aaa;">Nhập mã phiếu hoặc đơn hàng để tìm kiếm</div>
            </div>`;
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
                    container.innerHTML = `<div class="empty-state">Không tìm thấy phiếu nào chứa "${query}"</div>`;
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
                        setTimeout(() => {
                            const el = document.getElementById(`receive-p-${autoIds[0]}`);
                            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        }, 200);
                    } else {
                        this.renderReceiveAccordion();
                        this.showMessage('receive-scan-result',
                            `Tìm thấy ${res.total} phiếu chứa "${query}"`, 'info');
                    }
                }
            } else {
                this.showMessage('receive-scan-result', res.error || 'Lỗi tìm kiếm', 'danger');
                this.playSound('error');
            }
        } catch (e) {
            console.error(e);
            this.showMessage('receive-scan-result', 'Lỗi kết nối', 'danger');
        }
    }

    renderReceiveAccordion(highlightIds = null) {
        const container = document.getElementById('receive-available-accordion');
        if (!container) return;
        container.innerHTML = '';

        // --- Pinned section: selected pickings NOT in current search results ---
        const groupedIds = new Set(
            this.receiveSoGroups.flatMap(g => (g.pickings || []).map(p => p.id))
        );
        const pinnedIds = Array.from(this.receiveSelectedIds).filter(
            id => !groupedIds.has(id) && this.receiveAvailableData[id]?.info
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
            pinnedIds.forEach(id => {
                const p = this.receiveAvailableData[id].info;
                const isExpanded = this.receiveExpandedPickingIds.has(id);
                const pickingEl = document.createElement('div');
                pickingEl.className = 'receive-picking-item selected pinned-selected';
                pickingEl.id = `receive-p-${p.id}`;
                pickingEl.innerHTML = `
                    <div class="receive-picking-header">
                        <div class="receive-picking-checkbox checked" data-id="${p.id}"><i class="fa fa-check"></i></div>
                        <div class="receive-picking-info" data-id="${p.id}" style="flex:1;min-width:0;">
                            <div class="receive-picking-name">${p.name}</div>
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
                pickingEl.querySelector('.receive-picking-checkbox').addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.toggleReceivePickingSelection(p.id);
                });
                pickingEl.querySelector('.receive-picking-info').addEventListener('click', () => {
                    this.toggleReceivePickingSelection(p.id);
                });
                pickingEl.querySelector('.receive-expand-btn').addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.toggleReceivePickingExpand(p.id);
                });
                pinnedContent.appendChild(pickingEl);
            });
            container.appendChild(pinnedEl);
        }

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
            (group.pickings || []).forEach(p => {
                const isSelected = this.receiveSelectedIds.has(p.id);
                const isExpanded = this.receiveExpandedPickingIds.has(p.id);
                const isHighlighted = !!(highlightIds && highlightIds.includes(p.id));

                const pickingEl = document.createElement('div');
                pickingEl.className = `receive-picking-item${isSelected ? ' selected' : ''}${isHighlighted ? ' highlighted' : ''}`;
                pickingEl.id = `receive-p-${p.id}`;

                pickingEl.innerHTML = `
                    <div class="receive-picking-header">
                        <div class="receive-picking-checkbox${isSelected ? ' checked' : ''}" data-id="${p.id}">
                            <i class="fa fa-check"></i>
                        </div>
                        <div class="receive-picking-info" data-id="${p.id}" style="flex:1;min-width:0;">
                            <div class="receive-picking-name">${p.name}</div>
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

                pickingEl.querySelector('.receive-picking-checkbox').addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.toggleReceivePickingSelection(p.id);
                });
                pickingEl.querySelector('.receive-picking-info').addEventListener('click', () => {
                    this.toggleReceivePickingSelection(p.id);
                });
                pickingEl.querySelector('.receive-expand-btn').addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.toggleReceivePickingExpand(p.id);
                });

                contentDiv.appendChild(pickingEl);
            });

            container.appendChild(groupEl);
        });

        // Load-more footer
        const shownCount = this.receiveSoGroups.reduce((s, g) => s + (g.pickings || []).length, 0);
        const footerEl = document.createElement('div');
        footerEl.className = 'receive-list-footer';
        footerEl.innerHTML = `
            <span class="receive-list-count">Hiển thị ${shownCount} / ${this.receiveLoadTotal || shownCount} phiếu</span>
            ${this.receiveHasMore
                ? `<button id="receive-load-more-btn" class="btn btn-outline btn-sm">Tải thêm</button>`
                : ''}
        `;
        container.appendChild(footerEl);
        if (this.receiveHasMore) {
            document.getElementById('receive-load-more-btn')?.addEventListener('click', () => this.loadMoreReceive());
        }
    }

    toggleReceivePickingSelection(pickingId) {
        if (this.receiveSelectedIds.has(pickingId)) {
            this.receiveSelectedIds.delete(pickingId);
        } else {
            this.receiveSelectedIds.add(pickingId);
        }
        const isSelected = this.receiveSelectedIds.has(pickingId);
        const el = document.getElementById(`receive-p-${pickingId}`);
        if (el) {
            el.classList.toggle('selected', isSelected);
            const cb = el.querySelector('.receive-picking-checkbox');
            if (cb) cb.classList.toggle('checked', isSelected);
        }
        this.updateReceiveConfirmBar();
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

        // Build chips for each selected picking
        const chips = Array.from(this.receiveSelectedIds).map(id => {
            const info = this.receiveAvailableData[id]?.info;
            const name = info?.name || `#${id}`;
            return `<span class="receive-chip">${name}<button class="receive-chip-remove" data-id="${id}" title="B\u1ecf ch\u1ecdn">&times;</button></span>`;
        }).join('');

        bar.innerHTML = `
            <div class="receive-chips-row">${chips}</div>
            <button id="confirm-receive-selected-btn" class="btn btn-success btn-sm">
                <i class="fa fa-check-circle"></i> X\u00e1c nh\u1eadn nh\u1eadn ${count} phi\u1ebfu
            </button>
        `;

        bar.querySelectorAll('.receive-chip-remove').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleReceivePickingSelection(parseInt(btn.dataset.id));
            });
        });
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
            }
        } catch (e) {
            console.error(e);
            this.showMessage('receive-scan-result', 'Lỗi kết nối server', 'danger');
            this.playSound('error');
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
            });

            // Expand button → show items (stopPropagation prevents selection)
            card.querySelector('.return-expand-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleReturnPickingExpand(p.id);
            });

            container.appendChild(card);
        });
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

        if (this.settings.return_require_detail_scan && selectedArray.length === 1) {
            this.returnPickingId = selectedArray[0];
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
        await this.doConfirmReturn([this.returnPickingId], this.returnReason);
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