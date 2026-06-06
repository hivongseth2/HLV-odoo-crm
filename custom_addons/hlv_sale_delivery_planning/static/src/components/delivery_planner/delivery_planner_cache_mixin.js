/** @odoo-module **/

export class DeliveryPlannerCacheMixin {
    _openCacheDB() {
        return new Promise((resolve, reject) => {
            const req = indexedDB.open(this._CACHE_DB, 1);
            req.onupgradeneeded = () => {
                const db = req.result;
                if (!db.objectStoreNames.contains(this._CACHE_STORE)) {
                    db.createObjectStore(this._CACHE_STORE);
                }
            };
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        });
    }

    _buildFilterKey() {
        return JSON.stringify({
            q: this.state.searchQuery.trim(),
            wh: this.state.filterWarehouseId,
            ds: this.state.filterDeliveryStatus,
            ss: this.state.filterStockStatus,
            ps: this.state.filterPackingStatus,
            df: this.state.filterDateFrom,
            dt: this.state.filterDateTo,
            ddf: this.state.filterDoneDateFrom,
            ddt: this.state.filterDoneDateTo,
            pdf: this.state.filterPODateFrom,
            pdt: this.state.filterPODateTo,
            pos: this.state.filterPOStatus,
            sc: this.state.filterSalerCode.trim(),
            htgh: this.state.filterHtgh.trim(),
            dtype: this.state.filterDeliveryType,
            tags: this.state.filterTagIds.join(','),
            comp: this.state.showCompleted,
            nt: this.state.filterNeedTransfer,
            no: this.state.filterNewOrders,
            pr: this.state.filterPrintStatus,
            sr: this.state.filterShipperReceived,
            vm: this.state.viewMode,
        });
    }

    async _saveToCache(result) {
        try {
            // Serialize through JSON to strip OWL reactive Proxy objects —
            // IndexedDB's structured clone algorithm cannot clone Proxies and
            // throws DataCloneError when state arrays are passed directly
            // (e.g. from _refreshSubset or _autoLoadAllRemaining).
            let orders, dashboardStats, warehouses, tags;
            try {
                orders = JSON.parse(JSON.stringify(result.orders || []));
                dashboardStats = result.dashboard_stats ? JSON.parse(JSON.stringify(result.dashboard_stats)) : undefined;
                warehouses = result.warehouses ? JSON.parse(JSON.stringify(result.warehouses)) : undefined;
                tags = result.tags ? JSON.parse(JSON.stringify(result.tags)) : undefined;
            } catch (serErr) {
                console.warn('[DP Cache] _saveToCache serialization failed:', serErr);
                return;
            }
            const db = await this._openCacheDB();
            const tx = db.transaction(this._CACHE_STORE, 'readwrite');
            tx.objectStore(this._CACHE_STORE).put({
                filterKey: this._buildFilterKey(),
                timestamp: Date.now(),
                kanbanBatchSize: this.state.kanbanBatchSize,
                data: {
                    dashboard_stats: dashboardStats,
                    orders: orders,
                    total_count: result.total_count,
                    warehouses: warehouses,
                    tags: tags,
                },
            }, 'latest');
            await new Promise((resolve, reject) => {
                tx.oncomplete = () => resolve();
                tx.onerror = () => reject(tx.error);
            });
            db.close();
            console.log('[DP Cache] Saved', orders.length, 'orders to IndexedDB');
        } catch (e) {
            console.warn('[DP Cache] _saveToCache failed:', e);
        }
    }

    async _loadFromCache() {
        try {
            const db = await this._openCacheDB();
            return new Promise((resolve) => {
                const tx = db.transaction(this._CACHE_STORE, 'readonly');
                const req = tx.objectStore(this._CACHE_STORE).get('latest');
                req.onsuccess = () => {
                    db.close();
                    const payload = req.result;
                    if (!payload) { console.log('[DP Cache] No cached data found'); return resolve(null); }
                    if (payload.filterKey !== this._buildFilterKey()) { console.log('[DP Cache] Filter key mismatch, skipping cache'); return resolve(null); }
                    if (Date.now() - payload.timestamp > this._CACHE_TTL) { console.log('[DP Cache] Cache expired'); return resolve(null); }
                    // Restore kanbanBatchSize so "tải thêm" data persists
                    if (payload.kanbanBatchSize) {
                        this.state.kanbanBatchSize = payload.kanbanBatchSize;
                    }
                    console.log('[DP Cache] Restored', (payload.data.orders || []).length, 'orders (batchSize=' + (payload.kanbanBatchSize || '?') + ') from IndexedDB');
                    resolve(payload.data);
                };
                req.onerror = () => { db.close(); console.warn('[DP Cache] _loadFromCache read error'); resolve(null); };
            });
        } catch (e) {
            console.warn('[DP Cache] _loadFromCache failed:', e);
            return null;
        }
    }
}
