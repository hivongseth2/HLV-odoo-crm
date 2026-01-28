// hlv_barcode_shipper/static/src/js/barcode_scanner.js
/**
 * HLV Barcode Shipper JavaScript (Refactored for SO Grouping)
 */

class BarcodeShipper {
    constructor() {
        // Multi-picking state
        this.pickingDataMap = {};       // Map: pickingId -> { info, items, progress, so_name }
        this.soGroups = [];             // List of SO groups for rendering
        this.activePickingId = null;    // Current focused picking
        this.customerName = '';

        this.scannedBarcodes = new Set();
        this.html5QrCode = null;
        this.isCameraRunning = false;
        this.currentCameraSection = null;

        this.sessionId = this.generateSessionId();
        this.init();
    }

    generateSessionId() {
        return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    init() {
        this.bindEvents();
        this.setupBarcodeInputs();
        this.showStep('step-scan-pick');

        // Reload warning
        window.addEventListener('beforeunload', (e) => {
            if (Object.keys(this.pickingDataMap).length > 0) {
                const msg = '⚠️ CẢNH BÁO: Tiến độ quét sẽ bị MẤT nếu bạn tải lại trang!';
                e.preventDefault();
                e.returnValue = msg;
                return msg;
            }
        });
    }

    bindEvents() {
        // Buttons
        document.getElementById('scan-pick-btn')?.addEventListener('click', () => this.scanPickOrder());
        document.getElementById('scan-item-btn')?.addEventListener('click', () => this.scanItem());
        document.getElementById('complete-all-btn')?.addEventListener('click', () => this.completeAllDelivery());
        document.getElementById('reset-scan-btn')?.addEventListener('click', () => this.resetScan());
        document.getElementById('new-delivery-btn')?.addEventListener('click', () => this.startNewDelivery());
        document.getElementById('show-history-btn')?.addEventListener('click', () => this.showHistory());
        document.getElementById('help-btn')?.addEventListener('click', () => this.showHelp());

        // Camera Buttons (Manual)
        document.getElementById('btn-open-camera-pick')?.addEventListener('click', () => this.startCamera('camera-pick', 'reader-pick', 'pick'));
        document.getElementById('btn-open-camera-item')?.addEventListener('click', () => this.startCamera('camera-item', 'reader-item', 'item'));

        // Modals
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
        const pickInput = document.getElementById('pick-barcode-input');
        const itemInput = document.getElementById('item-barcode-input');

        if (pickInput) {
            pickInput.addEventListener('keypress', e => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    this.scanPickOrder();
                }
            });
        }

        if (itemInput) {
            itemInput.addEventListener('keypress', e => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    this.scanItem();
                }
            });
        }

        this.focusCurrentInput();
    }

    focusCurrentInput() {
        setTimeout(() => {
            const step = document.querySelector('.scan-step.active');
            const input = step && step.querySelector('.form-control');
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
        try {
            const soundPath = type === 'success'
                ? '/custom_barcode_scan_redirect/static/src/sound/success.mp3'
                : '/custom_barcode_scan_redirect/static/src/sound/error.mp3';
            new Audio(soundPath).play().catch(() => { });
        } catch (e) {
            console.warn('Sound play failed:', e);
        }
    }

    // --- Camera Logic ---
    async startCamera(sectionId, readerId, mode) {
        if (this.isCameraRunning && this.currentCameraSection === sectionId) return;

        if (this.isCameraRunning) await this.stopCamera();

        const section = document.getElementById(sectionId);
        if (section) section.classList.add('active');
        this.currentCameraSection = sectionId;

        // Hide manual button if auto-started
        if (mode === 'pick') {
            const btn = document.getElementById('btn-open-camera-pick');
            if (btn) btn.style.display = 'none';
        } else if (mode === 'item') {
            const btn = document.getElementById('btn-open-camera-item');
            if (btn) btn.style.display = 'none';
        }

        this.html5QrCode = new Html5Qrcode(readerId);
        const config = { fps: 10, qrbox: { width: 280, height: 150 } };

        try {
            await this.html5QrCode.start(
                { facingMode: "environment" },
                config,
                (decodedText, decodedResult) => this.onScanSuccess(decodedText, mode),
                (errorMessage) => { }
            );
            this.isCameraRunning = true;
        } catch (err) {
            console.error("Error starting camera", err);
            // Show manual button if camera fails
            if (mode === 'pick') {
                document.getElementById('btn-open-camera-pick').style.display = 'block';
            } else if (mode === 'item') {
                document.getElementById('btn-open-camera-item').style.display = 'block';
            }
            section.classList.remove('active');
        }
    }

    async stopCamera() {
        if (this.html5QrCode && this.isCameraRunning) {
            try {
                await this.html5QrCode.stop();
                this.html5QrCode.clear();
                this.isCameraRunning = false;
                this.currentCameraSection = null;
            } catch (e) {
                console.error("Failed to stop camera", e);
            }
        }
        document.querySelectorAll('.camera-section').forEach(el => el.classList.remove('active'));

        const btnPick = document.getElementById('btn-open-camera-pick');
        const btnItem = document.getElementById('btn-open-camera-item');
        if (btnPick) btnPick.style.display = 'block';
        if (btnItem) btnItem.style.display = 'block';
    }

    onScanSuccess(decodedText, mode) {
        if (mode === 'pick') {
            const input = document.getElementById('pick-barcode-input');
            if (input) {
                input.value = decodedText;
                this.scanPickOrder();
                this.stopCamera();
            }
        } else if (mode === 'item') {
            const input = document.getElementById('item-barcode-input');
            if (input) {
                input.value = decodedText;
                this.scanItem();
                this.html5QrCode.pause();
                setTimeout(() => this.html5QrCode.resume(), 200);
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
                this.showStep('step-scan-items');
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
                this.showStep('step-complete');
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

        this.showStep('step-scan-pick');
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