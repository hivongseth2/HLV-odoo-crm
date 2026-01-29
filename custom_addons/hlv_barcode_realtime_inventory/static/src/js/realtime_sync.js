/** @odoo-module **/

import BarcodeModel from "@stock_barcode/models/barcode_model";
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Generate device fingerprint (persist across sessions)
 */
function getDeviceId() {
    let id = localStorage.getItem('hlv_device_id');
    if (!id) {
        id = 'dev_' + crypto.randomUUID();
        localStorage.setItem('hlv_device_id', id);
        console.log(`[Realtime] New device ID created: ${id}`);
    }
    return id;
}

/**
 * Generate session ID per inventory operation (persist in sessionStorage)
 */
function getSessionId(inventoryContext) {
    // Tạo key duy nhất dựa trên location hoặc record ID
    const key = `hlv_inv_session_${inventoryContext}`;
    let id = sessionStorage.getItem(key);
    if (!id) {
        id = 'sess_' + crypto.randomUUID();
        sessionStorage.setItem(key, id);
        console.log(`[Realtime] New session ID created: ${id}`);
    }
    return id;
}

/**
 * Kiểm tra xem hiện tại có đang trong barcode view cho inventory không
 * Không check action ID cụ thể mà dựa vào URL pattern và context
 */
function isInventoryBarcodeView() {
    const url = window.location.href;

    // Check cho các barcode views liên quan đến inventory
    // Pattern 1: stock_barcode actions
    if (url.includes('stock_barcode')) return true;

    // Pattern 2: Bất kỳ action nào có model là stock.quant
    if (url.includes('model=stock.quant')) return true;

    // Pattern 3: Check view type là barcode/client_action
    if (url.includes('view_type=form') && url.includes('barcode')) return true;

    // Pattern 4: Legacy check cho action có chứa inventory
    if (url.includes('action=') && document.querySelector('.o_barcode_client_action')) return true;

    return false;
}

/**
 * Create or update UI indicator badge
 */
function updateIndicator(message, type = 'info') {
    let badge = document.querySelector('.hlv-realtime-indicator');
    if (!badge) {
        badge = document.createElement('div');
        badge.className = 'hlv-realtime-indicator';
        badge.style.cssText = `
            position: fixed;
            top: 60px;
            right: 20px;
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 12px;
            font-weight: bold;
            z-index: 9999;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            transition: all 0.3s ease;
        `;
        document.body.appendChild(badge);
    }

    // Style theo type
    const styles = {
        'success': 'background: #d4edda; color: #155724; border: 1px solid #c3e6cb;',
        'error': 'background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb;',
        'info': 'background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb;',
        'syncing': 'background: #fff3cd; color: #856404; border: 1px solid #ffeeba;'
    };

    badge.style.cssText += styles[type] || styles.info;
    badge.innerHTML = message;

    // Auto hide sau 5s nếu là success
    if (type === 'success') {
        setTimeout(() => {
            badge.style.opacity = '0';
            setTimeout(() => badge.remove(), 300);
        }, 5000);
    }
}

/**
 * Show sync status persistently
 */
function showSyncStatus(totalScans, lastProduct = '') {
    updateIndicator(
        `🔄 Real-time sync: ${totalScans} scans<br/>
        <small style="opacity: 0.8">${lastProduct}</small>`,
        'info'
    );
}

// ============================================================================
// PATCH BarcodeModel - LUÔN LUÔN ACTIVE KHI TRONG BARCODE VIEW
// ============================================================================

patch(BarcodeModel.prototype, {
    setup() {
        super.setup(...arguments);

        // Luôn initialize - sẽ check context khi scan
        this._deviceId = getDeviceId();
        this._sessionId = null;
        this._syncCount = 0;
        this._realtimeEnabled = true; // Enable by default

        console.log(
            '%c[HLV Realtime Inventory] Module ACTIVE - Real-time sync enabled',
            'padding:4px 8px;border-radius:4px;background:#0c5460;color:#d1ecf1;font-weight:bold'
        );

        // Show indicator khi vào barcode view
        setTimeout(() => {
            updateIndicator('✅ Real-time sync ACTIVE', 'success');
        }, 500);
    },

    /**
     * Override processBarcode để sync real-time
     */
    async processBarcode(barcode) {
        // Cho Odoo xử lý trước
        const result = await super.processBarcode(...arguments);

        // Nếu không scan được hoặc là command, bỏ qua
        if (!barcode || barcode.startsWith("O-CMD")) {
            return result;
        }

        // Identify product
        const product = await this._identifyProductSafe(barcode);
        if (!product) {
            console.warn('[Realtime] Could not identify product:', barcode);
            return result;
        }

        // Lấy location context
        const locationId = this.location?.id || null;
        const recordId = this.record?.id || Date.now();

        // Generate session ID if not exists
        if (!this._sessionId) {
            this._sessionId = getSessionId(locationId || recordId);
        }

        // Sync to backend
        try {
            updateIndicator('⏳ Đang sync...', 'syncing');

            const syncResult = await rpc("/web/dataset/call_kw", {
                model: "inventory.scan.session",
                method: "register_scan",
                args: [
                    this._sessionId,
                    this._deviceId,
                    locationId,
                    product.id,
                    1  // qty per scan
                ],
                kwargs: {}
            });

            if (syncResult.success) {
                this._syncCount = syncResult.total_scans || (this._syncCount + 1);
                console.log(`✅ [Realtime] Synced #${this._syncCount}:`, product.display_name);

                showSyncStatus(this._syncCount, product.display_name);
            } else {
                throw new Error(syncResult.error || 'Unknown sync error');
            }

        } catch (error) {
            console.error('❌ [Realtime] Sync failed:', error);
            updateIndicator(`⚠️ Sync failed: ${error.message}`, 'error');
        }

        return result;
    },

    /**
     * Safe identify product
     */
    async _identifyProductSafe(barcode) {
        // Check trong cache
        if (this.cache?.products) {
            const p = Object.values(this.cache.products).find(
                p => p.barcode === barcode || p.default_code === barcode
            );
            if (p) return p;
        }

        // Check trong currentState.lines
        if (this.currentState?.lines) {
            const line = this.currentState.lines.find(l => {
                const pObj = l.product_id;
                if (typeof pObj === 'object') {
                    return pObj.barcode === barcode || pObj.default_code === barcode;
                }
                return false;
            });
            if (line) return line.product_id;
        }

        // Fallback: RPC search
        try {
            const orm = this.orm || this.env?.services?.orm;
            if (orm) {
                const domain = ['|', ['barcode', '=', barcode], ['default_code', '=', barcode]];
                const res = await orm.call(
                    "product.product",
                    "search_read",
                    [domain, ['id', 'display_name', 'uom_id', 'tracking', 'barcode', 'default_code']],
                    { limit: 1 }
                );
                if (res && res.length > 0) {
                    const pData = res[0];
                    return {
                        id: pData.id,
                        display_name: pData.display_name,
                        barcode: pData.barcode || barcode,
                        default_code: pData.default_code || barcode
                    };
                }
            }
        } catch (e) {
            console.warn('[Realtime] Product search failed:', e);
        }

        return null;
    }
});

console.log(
    '%c🚀 [HLV Realtime Inventory] Loaded successfully - ALL barcode views enabled',
    'padding:4px 8px;border-radius:4px;background:#155724;color:#d4edda;font-weight:bold'
);
