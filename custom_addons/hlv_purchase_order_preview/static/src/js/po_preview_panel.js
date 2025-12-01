/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { ListController } from "@web/views/list/list_controller";
import { onMounted, onPatched } from "@odoo/owl";

// Store reference to current controller for use in ListRenderer
let _hlvCurrentController = null;

// Filter state management with localStorage and URL persistence
const HLV_FILTER_STATE = {
    product: null,
    supplier: null,
    receipt: null,

    // Save to localStorage and URL
    save() {
        const state = {
            product: this.product,
            supplier: this.supplier,
            receipt: this.receipt
        };
        try {
            localStorage.setItem('hlv_po_filters', JSON.stringify(state));
            this._updateURL(state);
        } catch (e) {
            console.warn('[HLV] Failed to save filter state:', e);
        }
    },

    // Load from localStorage or URL
    load() {
        // First try URL params
        const urlState = this._loadFromURL();
        if (urlState.hasFilters) {
            this.product = urlState.product;
            this.supplier = urlState.supplier;
            this.receipt = urlState.receipt;
            return;
        }

        // Fallback to localStorage
        try {
            const saved = localStorage.getItem('hlv_po_filters');
            if (saved) {
                const state = JSON.parse(saved);
                this.product = state.product || null;
                this.supplier = state.supplier || null;
                this.receipt = state.receipt || null;
            }
        } catch (e) {
            console.warn('[HLV] Failed to load filter state:', e);
        }
    },

    // Update URL params
    _updateURL(state) {
        const url = new URL(window.location.href);

        if (state.product) {
            url.searchParams.set('hlv_product', state.product);
        } else {
            url.searchParams.delete('hlv_product');
        }

        if (state.supplier) {
            url.searchParams.set('hlv_supplier', state.supplier);
        } else {
            url.searchParams.delete('hlv_supplier');
        }

        if (state.receipt) {
            url.searchParams.set('hlv_receipt', state.receipt);
        } else {
            url.searchParams.delete('hlv_receipt');
        }

        window.history.replaceState({}, '', url.toString());
    },

    // Load from URL params
    _loadFromURL() {
        const url = new URL(window.location.href);
        const product = url.searchParams.get('hlv_product');
        const supplier = url.searchParams.get('hlv_supplier');
        const receipt = url.searchParams.get('hlv_receipt');

        return {
            product: product || null,
            supplier: supplier || null,
            receipt: receipt || null,
            hasFilters: !!(product || supplier || receipt)
        };
    },

    // Clear all filters
    clear() {
        this.product = null;
        this.supplier = null;
        this.receipt = null;
        this.save();
    }
};

/**
 * Format number as currency (Vietnamese locale)
 */
function fmtCurrency(env, value) {
    try {
        const lang = (env.services.user?.lang || "vi_VN").replace("_", "-");
        return new Intl.NumberFormat(lang).format(value ?? 0);
    } catch {
        return String(value ?? "");
    }
}

/**
 * Get receipt status label in Vietnamese
 */
function getReceiptStatusLabel(status) {
    const labels = {
        'pending': 'Chưa nhận',
        'partial': 'Đã nhận một phần',
        'full': 'Đã nhận hết'
    };
    return labels[status] || status || '';
}

/**
 * Get receipt status badge color
 */
function getReceiptStatusBadgeClass(status) {
    const classes = {
        'pending': 'bg-warning text-dark',
        'partial': 'bg-info text-dark',
        'full': 'bg-success text-white'
    };
    return classes[status] || 'bg-secondary';
}

/**
 * Show preview panel for a purchase order
 */
async function showPOPreviewPanel(env, resId) {
    const log = (...args) => console.log("[HLV][PO Preview]", ...args);
    const warn = (...args) => console.warn("[HLV][PO Preview]", ...args);
    const err = (...args) => console.error("[HLV][PO Preview]", ...args);

    log("showPOPreviewPanel called with resId:", resId);

    if (!resId) {
        env.services.notification.add("Không xác định được đơn mua hàng để xem nhanh.", { type: "warning" });
        return;
    }

    const orm = env.services.orm;

    // Remove any existing panels
    try {
        document.querySelectorAll(".hlv-po-preview-panel").forEach((n) => n.remove());
    } catch (e) {
        warn("cleanup failed (safe to ignore)", e);
    }

    // Build container
    const target = document.createElement("div");
    target.className = "hlv-po-preview-panel";
    target.innerHTML = `
        <div class="hlv-panel-header">
            <div class="hlv-title">Đang tải...</div>
            <button class="btn btn-sm btn-secondary hlv-close">Đóng</button>
        </div>
        <div class="hlv-panel-body">
            <div class="d-flex justify-content-center align-items-center h-100">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Đang tải...</span>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(target);

    const destroy = () => {
        try {
            target.remove();
            document.removeEventListener('keydown', handleEscape);
        } catch { }
    };
    target.querySelector(".hlv-close")?.addEventListener("click", destroy);

    // Close on Escape key
    const handleEscape = (e) => {
        if (e.key === 'Escape') {
            destroy();
        }
    };
    document.addEventListener('keydown', handleEscape);

    // Click outside to close
    target.addEventListener('click', (e) => {
        if (e.target === target) {
            destroy();
        }
    });

    try {
        log("RPC read(purchase.order) ->", resId);

        // Fetch purchase order data
        const [order] = await orm.read(
            "purchase.order",
            [resId],
            ["name", "partner_id", "state", "amount_total", "receipt_status", "date_planned"]
        );
        log("read OK", order);

        log("RPC search_read(purchase.order.line)");

        // Fetch order lines
        const lines = await orm.searchRead(
            "purchase.order.line",
            [["order_id", "=", resId]],
            ["product_id", "name", "product_qty", "qty_received", "price_unit", "price_subtotal", "product_uom"]
        );
        log("searchRead OK", { count: lines?.length });

        // Render header
        target.querySelector(".hlv-title").innerHTML = `
            <strong>${order?.name || "Đơn mua hàng"}</strong>
            <span class="text-muted ms-2">- ${order?.partner_id?.[1] || ""}</span>
        `;

        const body = target.querySelector(".hlv-panel-body");

        // Build order summary
        const plannedDate = order?.date_planned ? new Date(order.date_planned).toLocaleDateString('vi-VN') : '';
        const receiptStatusLabel = getReceiptStatusLabel(order?.receipt_status);
        const receiptStatusBadge = getReceiptStatusBadgeClass(order?.receipt_status);

        // Build product rows
        const rows = (lines || [])
            .map(
                (l) => `
            <tr>
                <td class="text-start">${(l.product_id && l.product_id[1]) || l.name || ""}</td>
                <td class="text-center">${l.product_uom?.[1] || ""}</td>
                <td class="text-end">${fmtCurrency(env, l.product_qty)}</td>
                <td class="text-end">${fmtCurrency(env, l.qty_received)}</td>
                <td class="text-end">${fmtCurrency(env, l.price_unit)}</td>
                <td class="text-end fw-bold">${fmtCurrency(env, l.price_subtotal)}</td>
            </tr>`
            )
            .join("");

        body.innerHTML = `
            <div class="row mb-3">
                <div class="col-md-6">
                    <small class="text-muted">Ngày hàng về dự kiến:</small>
                    <div class="fw-bold">${plannedDate || 'Chưa có'}</div>
                </div>
                <div class="col-md-6">
                    <small class="text-muted">Trạng thái nhập kho:</small>
                    <div><span class="badge ${receiptStatusBadge}">${receiptStatusLabel}</span></div>
                </div>
            </div>
            <div class="table-responsive">
                <table class="table table-sm table-striped table-hover mb-0">
                    <thead class="table-light">
                        <tr>
                            <th class="text-start">Sản phẩm</th>
                            <th class="text-center">ĐVT</th>
                            <th class="text-end">SL đặt</th>
                            <th class="text-end">SL nhận</th>
                            <th class="text-end">Đơn giá</th>
                            <th class="text-end">Thành tiền</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                    <tfoot class="table-light">
                        <tr>
                            <td colspan="5" class="text-end fw-bold">Tổng cộng:</td>
                            <td class="text-end fw-bold text-primary">${fmtCurrency(env, order?.amount_total)}</td>
                        </tr>
                    </tfoot>
                </table>
            </div>
        `;

        log("rendered successfully");

    } catch (e) {
        err("exception", e);
        env.services.notification.add("Không thể tải dữ liệu đơn mua hàng.", { type: "danger" });
        try { target?.remove(); } catch { }
    }
}

/**
 * Get record resId from row element in Odoo 18
 */
function getResIdFromRow(listRenderer, row) {
    const datapointId = row.dataset.id;
    if (!datapointId) return null;

    const records = listRenderer.props.list?.records || [];
    for (const record of records) {
        if (record.id === datapointId) {
            return record.resId;
        }
    }

    const parsed = parseInt(datapointId);
    if (!isNaN(parsed) && parsed > 0) {
        return parsed;
    }

    return null;
}

/**
 * Patch ListController to add custom search bar and store reference
 */
patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);

        if (this.props.resModel === 'purchase.order') {
            // Store controller reference for ListRenderer
            _hlvCurrentController = this;

            onMounted(() => {
                this._hlvAddCustomSearchBar();
                // Restore filters after mount
                this._hlvRestoreFilters();
                // Monitor filter changes
                this._hlvMonitorFilterChanges();
            });
            onPatched(() => {
                this._hlvAddCustomSearchBar();
                this._hlvSyncInputsWithState();
                this._hlvMonitorFilterChanges();
            });
        }
    },

    _hlvMonitorFilterChanges() {
        // Watch for filter removals in the search panel
        const searchPanel = document.querySelector('.o_searchview');
        if (!searchPanel || searchPanel.dataset.hlvMonitored) return;

        searchPanel.dataset.hlvMonitored = 'true';

        // Use MutationObserver to detect when facets are removed
        const observer = new MutationObserver(() => {
            this._hlvCheckFilterSync();
        });

        observer.observe(searchPanel, {
            childList: true,
            subtree: true
        });
    },

    _hlvCheckFilterSync() {
        const searchModel = this.env?.searchModel;
        if (!searchModel) return;

        const activeFilters = searchModel.searchItems || {};

        // Check if product filter was removed
        const hasProductFilter = Object.values(activeFilters).some(
            item => item.description && item.description.startsWith('SP:')
        );
        if (!hasProductFilter && HLV_FILTER_STATE.product) {
            console.log('[HLV] Product filter removed externally');
            HLV_FILTER_STATE.product = null;
            HLV_FILTER_STATE.save();
            this._hlvSyncInputsWithState();
        }

        // Check if supplier filter was removed
        const hasSupplierFilter = Object.values(activeFilters).some(
            item => item.description && item.description.startsWith('NCC:')
        );
        if (!hasSupplierFilter && HLV_FILTER_STATE.supplier) {
            console.log('[HLV] Supplier filter removed externally');
            HLV_FILTER_STATE.supplier = null;
            HLV_FILTER_STATE.save();
        }

        // Check if receipt filter was removed
        const hasReceiptFilter = Object.values(activeFilters).some(
            item => item.description && (
                item.description === 'Chưa nhận' ||
                item.description === 'Đã nhận một phần' ||
                item.description === 'Đã nhận hết'
            )
        );
        if (!hasReceiptFilter && HLV_FILTER_STATE.receipt) {
            console.log('[HLV] Receipt filter removed externally');
            HLV_FILTER_STATE.receipt = null;
            HLV_FILTER_STATE.save();
        }
    },

    _hlvRestoreFilters() {
        console.log('[HLV] Restoring filters from storage');
        HLV_FILTER_STATE.load();

        const searchModel = this.env?.searchModel;
        if (!searchModel || !searchModel.createNewFilters) {
            console.warn('[HLV] Cannot restore filters - searchModel not ready');
            return;
        }

        // Restore product filter
        if (HLV_FILTER_STATE.product) {
            const domain = [
                '|',
                ['order_line.product_id.name', '=ilike', HLV_FILTER_STATE.product],
                ['order_line.product_id.default_code', '=ilike', HLV_FILTER_STATE.product]
            ];
            searchModel.createNewFilters([{
                description: `SP: ${HLV_FILTER_STATE.product}`,
                domain: domain,
                type: 'filter',
            }]).catch(e => console.error('[HLV] Failed to restore product filter:', e));
        }

        // Restore supplier filter
        if (HLV_FILTER_STATE.supplier) {
            const domain = [['partner_id.name', '=ilike', `%${HLV_FILTER_STATE.supplier}%`]];
            searchModel.createNewFilters([{
                description: `NCC: ${HLV_FILTER_STATE.supplier}`,
                domain: domain,
                type: 'filter',
            }]).catch(e => console.error('[HLV] Failed to restore supplier filter:', e));
        }

        // Restore receipt filter
        if (HLV_FILTER_STATE.receipt) {
            const domain = [['receipt_status', '=', HLV_FILTER_STATE.receipt]];
            const label = getReceiptStatusLabel(HLV_FILTER_STATE.receipt);
            searchModel.createNewFilters([{
                description: label,
                domain: domain,
                type: 'filter',
            }]).catch(e => console.error('[HLV] Failed to restore receipt filter:', e));
        }

        // Sync input values
        this._hlvSyncInputsWithState();
    },

    _hlvSyncInputsWithState() {
        // Sync product input
        const productInput = document.querySelector('.hlv-product-search');
        if (productInput && productInput.value !== (HLV_FILTER_STATE.product || '')) {
            productInput.value = HLV_FILTER_STATE.product || '';
        }

        // Update clear button visibility
        const clearBtn = document.querySelector('.hlv-clear-product');
        if (clearBtn) {
            clearBtn.style.display = HLV_FILTER_STATE.product ? 'inline-block' : 'none';
        }
    },

    _hlvAddCustomSearchBar() {
        if (this.props.resModel !== 'purchase.order') return;

        const controlPanel = document.querySelector('.o_control_panel');
        if (!controlPanel) return;

        if (document.querySelector('.hlv-custom-search-bar')) return;

        const searchArea = controlPanel.querySelector('.o_searchview') ||
                          controlPanel.querySelector('.o_control_panel_main');
        if (!searchArea) return;

        const searchBar = document.createElement('div');
        searchBar.className = 'hlv-custom-search-bar d-flex gap-2 align-items-center';
        searchBar.style.cssText = 'margin-left: 24px;';
        searchBar.innerHTML = `
            <div class="hlv-search-group d-flex align-items-center">
                <label class="hlv-search-label me-2" style="font-weight: 500; color: #714B67; white-space: nowrap;">SP:</label>
                <input type="text" class="form-control form-control-sm hlv-product-search"
                       placeholder="Tìm sản phẩm trong đơn..." style="width: 200px;"
                       value="${HLV_FILTER_STATE.product || ''}">
                <button class="btn btn-sm btn-link hlv-clear-product" style="display: ${HLV_FILTER_STATE.product ? 'inline-block' : 'none'}; padding: 0 8px; color: #dc3545;" title="Xóa">
                    <i class="fa fa-times"></i>
                </button>
            </div>
        `;

        const parentEl = searchArea.parentElement;
        if (parentEl) {
            parentEl.insertBefore(searchBar, searchArea.nextSibling);
        }

        const productInput = searchBar.querySelector('.hlv-product-search');
        const clearBtn = searchBar.querySelector('.hlv-clear-product');

        productInput?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this._hlvSearchByProduct(productInput.value.trim());
            }
        });

        productInput?.addEventListener('input', () => {
            clearBtn.style.display = productInput.value ? 'inline-block' : 'none';
        });

        clearBtn?.addEventListener('click', (e) => {
            e.preventDefault();
            productInput.value = '';
            clearBtn.style.display = 'none';
            this._hlvSearchByProduct('');
        });
    },

    async _hlvSearchByProduct(value) {
        console.log('[HLV] Product search:', value);

        const searchModel = this.env.searchModel;

        if (!searchModel || !searchModel.createNewFilters) {
            console.error('[HLV] SearchModel or createNewFilters not available');
            return;
        }

        // Remove existing product search filter
        const existingFilters = searchModel.searchItems || {};
        for (const [id, item] of Object.entries(existingFilters)) {
            if (item.description && item.description.startsWith('SP:')) {
                searchModel.deactivateGroup(id);
            }
        }

        // Update state
        HLV_FILTER_STATE.product = value || null;
        HLV_FILTER_STATE.save();

        if (!value) {
            console.log('[HLV] Cleared product search');
            return;
        }

        // Create new filter with facet - using =ilike for accent-sensitive search
        const domain = [
            '|',
            ['order_line.product_id.name', '=ilike', `%${value}%`],
            ['order_line.product_id.default_code', '=ilike', `%${value}%`]
        ];

        try {
            await searchModel.createNewFilters([{
                description: `SP: ${value}`,
                domain: domain,
                type: 'filter',
            }]);
            console.log('[HLV] Applied product search with facet');
        } catch (e) {
            console.error('[HLV] Failed to create filter:', e);
        }
    }
});

/**
 * Patch ListRenderer to add preview button and filters
 */
patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);

        if (this.props.list?.resModel === 'purchase.order') {
            onMounted(() => {
                this._hlvAddReceiptStatusFilter();
                this._hlvAddSupplierHeaderSearch();
                this._hlvAddPreviewButtons();
            });
            onPatched(() => {
                this._hlvAddReceiptStatusFilter();
                this._hlvAddSupplierHeaderSearch();
                this._hlvAddPreviewButtons();
            });
        }
    },

    _hlvAddPreviewButtons() {
        if (this.props.list?.resModel !== 'purchase.order') return;

        const tableEl = this.tableRef?.el;
        if (!tableEl) return;

        const rows = tableEl.querySelectorAll('tbody tr.o_data_row');
        rows.forEach(row => {
            if (row.dataset.hlvPreviewAdded) return;
            row.dataset.hlvPreviewAdded = 'true';

            const resId = getResIdFromRow(this, row);
            if (!resId) {
                console.warn('[HLV] Could not get resId for row:', row.dataset.id);
                return;
            }

            const lastTd = row.querySelector('td:last-child');
            if (!lastTd) return;

            if (lastTd.querySelector('.hlv-preview-btn')) return;

            const btn = document.createElement('button');
            btn.className = 'btn btn-sm btn-outline-primary hlv-preview-btn ms-1';
            btn.innerHTML = '👁 Xem';
            btn.title = 'Xem sơ lược sản phẩm';
            btn.type = 'button';
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                showPOPreviewPanel(this.env, resId);
            });

            lastTd.appendChild(btn);
        });
    },

    _hlvAddSupplierHeaderSearch() {
        if (this.props.list?.resModel !== 'purchase.order') return;

        const tableEl = this.tableRef?.el;
        if (!tableEl) return;

        const partnerHeader = tableEl.querySelector('th[data-name="partner_id"]');
        if (!partnerHeader || partnerHeader.dataset.hlvSearchAdded) return;
        partnerHeader.dataset.hlvSearchAdded = 'true';

        const searchBtn = document.createElement('button');
        searchBtn.className = 'btn btn-link p-0 hlv-header-search-btn ms-1';
        searchBtn.type = 'button';
        searchBtn.title = 'Nhấn để tìm theo nhà cung cấp';
        searchBtn.innerHTML = '<i class="fa fa-search"></i>';

        searchBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this._hlvShowSupplierSearchPopup(searchBtn);
        });

        partnerHeader.appendChild(searchBtn);
    },

    _hlvShowSupplierSearchPopup(triggerBtn) {
        document.querySelectorAll('.hlv-search-popup').forEach(p => p.remove());

        const rect = triggerBtn.getBoundingClientRect();

        const popup = document.createElement('div');
        popup.className = 'hlv-search-popup';
        popup.style.cssText = `
            position: fixed;
            top: ${rect.bottom + 4}px;
            left: ${rect.left - 100}px;
            background: #fff;
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
            z-index: 10000;
            padding: 10px;
        `;
        popup.innerHTML = `
            <input type="text" class="form-control form-control-sm hlv-popup-input"
                   placeholder="Nhập tên nhà cung cấp..." autofocus style="width: 200px;">
            <div class="mt-2 text-muted small">Nhấn Enter để tìm</div>
        `;

        document.body.appendChild(popup);

        const input = popup.querySelector('.hlv-popup-input');
        input.focus();

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                const value = input.value.trim();
                popup.remove();
                this._hlvApplySupplierSearch(value);
            } else if (e.key === 'Escape') {
                popup.remove();
            }
        });

        setTimeout(() => {
            document.addEventListener('click', function closePopup(e) {
                if (!popup.contains(e.target) && e.target !== triggerBtn) {
                    popup.remove();
                    document.removeEventListener('click', closePopup);
                }
            });
        }, 10);
    },

    _hlvApplySupplierSearch(value) {
        console.log('[HLV] Supplier search:', value);

        const controller = _hlvCurrentController;
        if (!controller) {
            console.error('[HLV] Controller not available');
            return;
        }

        const searchModel = controller.env.searchModel;
        if (!searchModel || !searchModel.createNewFilters) {
            console.error('[HLV] SearchModel or createNewFilters not available');
            return;
        }

        // Remove existing supplier search filter
        const existingFilters = searchModel.searchItems || {};
        for (const [id, item] of Object.entries(existingFilters)) {
            if (item.description && item.description.startsWith('NCC:')) {
                searchModel.deactivateGroup(id);
            }
        }

        // Update state
        HLV_FILTER_STATE.supplier = value || null;
        HLV_FILTER_STATE.save();

        if (!value) {
            console.log('[HLV] Cleared supplier search');
            return;
        }

        // Create new filter with facet - using =ilike for accent-sensitive search
        const domain = [['partner_id.name', '=ilike', `%${value}%`]];

        searchModel.createNewFilters([{
            description: `NCC: ${value}`,
            domain: domain,
            type: 'filter',
        }]).catch(e => {
            console.error('[HLV] Failed to create supplier filter:', e);
        });
    },

    _hlvAddReceiptStatusFilter() {
        if (this.props.list?.resModel !== 'purchase.order') return;

        const tableEl = this.tableRef?.el;
        if (!tableEl) return;

        const receiptHeader = tableEl.querySelector('th[data-name="receipt_status"]');
        if (!receiptHeader || receiptHeader.dataset.hlvFilterAdded) return;
        receiptHeader.dataset.hlvFilterAdded = 'true';

        const filterBtn = document.createElement('button');
        filterBtn.className = 'btn btn-link p-0 hlv-filter-btn ms-1';
        filterBtn.type = 'button';
        filterBtn.title = 'Nhấn để lọc theo trạng thái';
        filterBtn.innerHTML = '<i class="fa fa-filter"></i>';

        filterBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this._hlvShowReceiptFilterDropdown(filterBtn);
        });

        receiptHeader.appendChild(filterBtn);
    },

    _hlvShowReceiptFilterDropdown(triggerBtn) {
        document.querySelectorAll('.hlv-filter-dropdown-portal').forEach(d => d.remove());

        const rect = triggerBtn.getBoundingClientRect();

        const dropdown = document.createElement('div');
        dropdown.className = 'hlv-filter-dropdown-portal';
        dropdown.style.cssText = `
            position: fixed;
            top: ${rect.bottom + 4}px;
            left: ${rect.left - 80}px;
            min-width: 160px;
            background: #fff;
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
            z-index: 10000;
            overflow: hidden;
        `;

        const items = [
            { value: 'pending', label: 'Chưa nhận', color: '#ffc107' },
            { value: 'partial', label: 'Đã nhận một phần', color: '#17a2b8' },
            { value: 'full', label: 'Đã nhận hết', color: '#28a745' },
            { value: '', label: '— Tất cả —', color: '#714B67' }
        ];

        items.forEach((item, idx) => {
            const div = document.createElement('div');
            div.className = 'hlv-filter-dropdown-item';

            // Add color indicator dot
            const colorDot = item.color ? `<span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: ${item.color}; margin-right: 8px;"></span>` : '';

            div.innerHTML = colorDot + item.label;
            div.style.cssText = `
                padding: 10px 16px;
                cursor: pointer;
                font-size: 0.9rem;
                color: ${item.value === '' ? '#714B67' : '#333'};
                font-weight: ${item.value === '' ? '600' : '400'};
                border-bottom: ${idx < items.length - 1 ? '1px solid #f0f0f0' : 'none'};
                transition: background-color 0.15s;
                display: flex;
                align-items: center;
            `;
            div.addEventListener('mouseenter', () => {
                div.style.backgroundColor = '#f8f4f7';
            });
            div.addEventListener('mouseleave', () => {
                div.style.backgroundColor = '';
            });
            div.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropdown.remove();
                this._hlvApplyReceiptFilter(item.value);
            });
            dropdown.appendChild(div);
        });

        document.body.appendChild(dropdown);

        const closeHandler = (e) => {
            if (!dropdown.contains(e.target) && e.target !== triggerBtn) {
                dropdown.remove();
                document.removeEventListener('click', closeHandler);
            }
        };
        setTimeout(() => {
            document.addEventListener('click', closeHandler);
        }, 10);

        const scrollHandler = () => {
            dropdown.remove();
            document.removeEventListener('scroll', scrollHandler, true);
        };
        document.addEventListener('scroll', scrollHandler, true);
    },

    _hlvApplyReceiptFilter(value) {
        console.log('[HLV] Receipt filter:', value);

        const controller = _hlvCurrentController;
        if (!controller) {
            console.error('[HLV] Controller not available');
            return;
        }

        const searchModel = controller.env.searchModel;
        if (!searchModel || !searchModel.createNewFilters) {
            console.error('[HLV] SearchModel or createNewFilters not available');
            return;
        }

        // Remove existing receipt filter
        const existingFilters = searchModel.searchItems || {};
        for (const [id, item] of Object.entries(existingFilters)) {
            if (item.description && (
                item.description === 'Chưa nhận' ||
                item.description === 'Đã nhận một phần' ||
                item.description === 'Đã nhận hết'
            )) {
                searchModel.deactivateGroup(id);
            }
        }

        // Update state
        HLV_FILTER_STATE.receipt = value || null;
        HLV_FILTER_STATE.save();

        if (!value) {
            console.log('[HLV] Cleared receipt filter');
            return;
        }

        // Create new filter with facet
        const domain = [['receipt_status', '=', value]];
        const label = getReceiptStatusLabel(value);

        searchModel.createNewFilters([{
            description: label,
            domain: domain,
            type: 'filter',
        }]).catch(e => {
            console.error('[HLV] Failed to create receipt filter:', e);
        });
    }
});
