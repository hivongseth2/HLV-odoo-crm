/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { ListController } from "@web/views/list/list_controller";
import { onMounted, onPatched } from "@odoo/owl";

// Store reference to current controller for use in ListRenderer
let _hlvCurrentController = null;

// Store active HLV filters - supports multiple values per type for OR combination
// Same type = OR, Different types = AND
let _hlvActiveFilters = {
    supplier: [],       // Array of { value: string, domain: array }
    receiptStatus: [],  // Array of { value: string, label: string, domain: array }
    product: []         // Array of { value: string, domain: array }
};

/**
 * Build OR domain from multiple domains
 */
function buildOrDomain(domains) {
    if (domains.length === 0) return [];
    if (domains.length === 1) return domains[0];

    // For OR combination: need (n-1) '|' operators
    const result = [];
    for (let i = 0; i < domains.length - 1; i++) {
        result.push('|');
    }
    for (const domain of domains) {
        result.push(...domain);
    }
    return result;
}

/**
 * Apply combined HLV filters using:
 * - OR for same type (multiple suppliers, multiple statuses)
 * - AND for different types (supplier AND status AND product)
 */
function applyHlvCombinedFilters(searchModel) {
    if (!searchModel || !searchModel.createNewFilters) return;

    // Remove existing HLV combined filter
    const existingFilters = searchModel.searchItems || {};
    for (const [id, item] of Object.entries(existingFilters)) {
        if (item.description && item.description.startsWith('HLV:')) {
            searchModel.deactivateGroup(id);
        }
    }

    // Build domain for each filter type (OR within same type)
    const typeFilters = [];
    const labelParts = [];

    // Supplier filters (OR)
    if (_hlvActiveFilters.supplier.length > 0) {
        const supplierDomains = _hlvActiveFilters.supplier.map(f => f.domain);
        typeFilters.push(buildOrDomain(supplierDomains));
        const supplierLabels = _hlvActiveFilters.supplier.map(f => f.value).join(' | ');
        labelParts.push(`NCC: ${supplierLabels}`);
    }

    // Receipt status filters (OR)
    if (_hlvActiveFilters.receiptStatus.length > 0) {
        const statusDomains = _hlvActiveFilters.receiptStatus.map(f => f.domain);
        typeFilters.push(buildOrDomain(statusDomains));
        const statusLabels = _hlvActiveFilters.receiptStatus.map(f => f.label).join(' | ');
        labelParts.push(statusLabels);
    }

    // Product filters (OR)
    if (_hlvActiveFilters.product.length > 0) {
        const productDomains = _hlvActiveFilters.product.map(f => f.domain);
        typeFilters.push(buildOrDomain(productDomains));
        const productLabels = _hlvActiveFilters.product.map(f => f.value).join(' | ');
        labelParts.push(`SP: ${productLabels}`);
    }

    if (typeFilters.length === 0) {
        console.log('[HLV] All filters cleared');
        return;
    }

    // Combine different types with AND (just concatenate domains)
    let combinedDomain = [];
    for (const typeDomain of typeFilters) {
        combinedDomain.push(...typeDomain);
    }

    const description = 'HLV: ' + labelParts.join(' & ');
    console.log('[HLV] Combined filter (OR within type, AND between types):', description, combinedDomain);

    try {
        searchModel.createNewFilters([{
            description: description,
            domain: combinedDomain,
            type: 'filter',
        }]);
    } catch (e) {
        console.error('[HLV] Failed to create combined filter:', e);
    }
}

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
                this._hlvMonitorFilterChanges();
            });
            onPatched(() => {
                this._hlvAddCustomSearchBar();
                this._hlvSyncProductInput();
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
            this._hlvSyncProductInput();
        });

        observer.observe(searchPanel, {
            childList: true,
            subtree: true
        });
    },

    _hlvSyncProductInput() {
        // Sync product input with current filter state
        const productInput = document.querySelector('.hlv-product-search');
        const clearBtn = document.querySelector('.hlv-clear-product');
        if (!productInput) return;

        // Check if HLV filter was removed from search panel
        const searchModel = this.env?.searchModel;
        if (searchModel) {
            const existingFilters = searchModel.searchItems || {};
            let hlvFilterExists = false;
            for (const item of Object.values(existingFilters)) {
                if (item.description && item.description.startsWith('HLV:')) {
                    hlvFilterExists = true;
                    break;
                }
            }
            // If HLV filter was removed, clear all active filters
            const hasActiveFilters = _hlvActiveFilters.product.length > 0 ||
                                     _hlvActiveFilters.supplier.length > 0 ||
                                     _hlvActiveFilters.receiptStatus.length > 0;
            if (!hlvFilterExists && hasActiveFilters) {
                _hlvActiveFilters.product = [];
                _hlvActiveFilters.supplier = [];
                _hlvActiveFilters.receiptStatus = [];
                productInput.value = '';
                if (clearBtn) clearBtn.style.display = 'none';
                return;
            }
        }

        // For product, we only show one value in input (latest)
        const currentValue = _hlvActiveFilters.product.length > 0
            ? _hlvActiveFilters.product.map(f => f.value).join(', ')
            : '';

        if (productInput.value !== currentValue) {
            productInput.value = currentValue;
        }

        if (clearBtn) {
            clearBtn.style.display = currentValue ? 'inline-block' : 'none';
        }
    },

    _hlvAddCustomSearchBar() {
        if (this.props.resModel !== 'purchase.order') return;

        const controlPanel = document.querySelector('.o_control_panel');
        if (!controlPanel) return;

        if (document.querySelector('.hlv-custom-search-bar')) return;

        // Find the buttons area (right side of control panel) to insert before it
        const buttonsArea = controlPanel.querySelector('.o_control_panel_actions') ||
                           controlPanel.querySelector('.o_cp_action_menus');

        // Or find the breadcrumb area to insert after
        const breadcrumbArea = controlPanel.querySelector('.o_control_panel_breadcrumbs');

        const searchBar = document.createElement('div');
        searchBar.className = 'hlv-custom-search-bar d-flex gap-2 align-items-center';
        searchBar.style.cssText = 'margin-left: auto; margin-right: 16px;';

        // Get current filter value from active filters
        const currentValue = _hlvActiveFilters.product.length > 0
            ? _hlvActiveFilters.product.map(f => f.value).join(', ')
            : '';

        searchBar.innerHTML = `
            <div class="hlv-search-group d-flex align-items-center">
                <label class="hlv-search-label me-2" style="font-weight: 500; color: #714B67; white-space: nowrap;">SP:</label>
                <input type="text" class="form-control form-control-sm hlv-product-search"
                       placeholder="Tìm sản phẩm trong đơn..." style="width: 200px;"
                       value="${currentValue}">
                <button class="btn btn-sm btn-link hlv-clear-product" style="display: ${currentValue ? 'inline-block' : 'none'}; padding: 0 8px; color: #dc3545;" title="Xóa">
                    <i class="fa fa-times"></i>
                </button>
            </div>
        `;

        // Insert in the control panel navigation area, not inside searchview
        if (buttonsArea && buttonsArea.parentElement) {
            buttonsArea.parentElement.insertBefore(searchBar, buttonsArea);
        } else if (breadcrumbArea && breadcrumbArea.parentElement) {
            // Fallback: insert after breadcrumb
            breadcrumbArea.parentElement.appendChild(searchBar);
        } else {
            // Last fallback: append to control panel main
            const mainArea = controlPanel.querySelector('.o_control_panel_main');
            if (mainArea) {
                mainArea.appendChild(searchBar);
            }
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

        if (!value) {
            _hlvActiveFilters.product = [];
            console.log('[HLV] Cleared product search');
        } else {
            // Create domain for product search (replace existing)
            const domain = [
                '|',
                ['order_line.product_id.name', 'ilike', `%${value}%`],
                ['order_line.product_id.default_code', 'ilike', `%${value}%`]
            ];
            // Product search replaces existing (single input field)
            _hlvActiveFilters.product = [{ value: value, domain: domain }];
        }

        // Apply combined filters
        applyHlvCombinedFilters(searchModel);
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

        // Wrap header content in flex container for inline display
        const headerContent = partnerHeader.innerHTML;
        partnerHeader.innerHTML = '';
        partnerHeader.style.cssText = 'white-space: nowrap;';

        const wrapper = document.createElement('div');
        wrapper.className = 'd-flex align-items-center gap-1';
        wrapper.innerHTML = headerContent;

        const searchBtn = document.createElement('button');
        searchBtn.className = 'btn btn-link p-0 hlv-header-search-btn';
        searchBtn.type = 'button';
        searchBtn.title = 'Nhấn để tìm theo nhà cung cấp';
        searchBtn.innerHTML = '<i class="fa fa-search" style="font-size: 11px;"></i>';
        searchBtn.style.cssText = 'line-height: 1; opacity: 0.7;';

        searchBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this._hlvShowSupplierSearchPopup(searchBtn);
        });

        wrapper.appendChild(searchBtn);
        partnerHeader.appendChild(wrapper);
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

    async _hlvApplySupplierSearch(value) {
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

        if (!value) {
            _hlvActiveFilters.supplier = [];
            console.log('[HLV] Cleared supplier search');
            applyHlvCombinedFilters(searchModel);
            return;
        }

        // Check if this supplier is already in the filter
        const existingIndex = _hlvActiveFilters.supplier.findIndex(f => f.value === value);
        if (existingIndex >= 0) {
            console.log('[HLV] Supplier already in filter, skipping');
            return;
        }

        // Use Python method to search with exact Vietnamese diacritic matching
        try {
            const orm = controller.env.services.orm;
            const matchingIds = await orm.call(
                'purchase.order',
                'search_supplier_exact',
                [value, null]
            );

            console.log('[HLV] Supplier search found IDs:', matchingIds);

            // Create filter with exact ID list
            const domain = matchingIds.length > 0
                ? [['id', 'in', matchingIds]]
                : [['id', '=', -1]]; // No results

            // Add to existing suppliers (OR combination)
            _hlvActiveFilters.supplier.push({ value: value, domain: domain });
            applyHlvCombinedFilters(searchModel);
        } catch (e) {
            console.error('[HLV] Failed to search supplier:', e);
            // Fallback to ilike search
            const domain = [['partner_id.name', 'ilike', `%${value}%`]];
            _hlvActiveFilters.supplier.push({ value: value, domain: domain });
            applyHlvCombinedFilters(searchModel);
        }
    },

    _hlvAddReceiptStatusFilter() {
        if (this.props.list?.resModel !== 'purchase.order') return;

        const tableEl = this.tableRef?.el;
        if (!tableEl) return;

        const receiptHeader = tableEl.querySelector('th[data-name="receipt_status"]');
        if (!receiptHeader || receiptHeader.dataset.hlvFilterAdded) return;
        receiptHeader.dataset.hlvFilterAdded = 'true';

        // Wrap header content in flex container for inline display
        const headerContent = receiptHeader.innerHTML;
        receiptHeader.innerHTML = '';
        receiptHeader.style.cssText = 'white-space: nowrap;';

        const wrapper = document.createElement('div');
        wrapper.className = 'd-flex align-items-center gap-1';
        wrapper.innerHTML = headerContent;

        const filterBtn = document.createElement('button');
        filterBtn.className = 'btn btn-link p-0 hlv-filter-btn';
        filterBtn.type = 'button';
        filterBtn.title = 'Nhấn để lọc theo trạng thái';
        filterBtn.innerHTML = '<i class="fa fa-filter" style="font-size: 11px;"></i>';
        filterBtn.style.cssText = 'line-height: 1; opacity: 0.7;';

        filterBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this._hlvShowReceiptFilterDropdown(filterBtn);
        });

        wrapper.appendChild(filterBtn);
        receiptHeader.appendChild(wrapper);
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

            // Check if this status is currently selected
            const isSelected = item.value && _hlvActiveFilters.receiptStatus.some(f => f.value === item.value);

            // Add checkbox for status items, color dot for visual
            const checkbox = item.value ? `<span style="display: inline-block; width: 16px; height: 16px; border: 1px solid #ccc; border-radius: 3px; margin-right: 8px; text-align: center; line-height: 14px; font-size: 11px; background: ${isSelected ? '#714B67' : '#fff'}; color: #fff;">${isSelected ? '✓' : ''}</span>` : '';
            const colorDot = item.color ? `<span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: ${item.color}; margin-right: 8px;"></span>` : '';

            div.innerHTML = checkbox + colorDot + item.label;
            div.style.cssText = `
                padding: 10px 16px;
                cursor: pointer;
                font-size: 0.9rem;
                color: ${item.value === '' ? '#714B67' : '#333'};
                font-weight: ${item.value === '' ? '600' : (isSelected ? '600' : '400')};
                border-bottom: ${idx < items.length - 1 ? '1px solid #f0f0f0' : 'none'};
                transition: background-color 0.15s;
                display: flex;
                align-items: center;
                background-color: ${isSelected ? '#f8f4f7' : ''};
            `;
            div.addEventListener('mouseenter', () => {
                div.style.backgroundColor = '#f8f4f7';
            });
            div.addEventListener('mouseleave', () => {
                div.style.backgroundColor = isSelected ? '#f8f4f7' : '';
            });
            div.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (item.value === '') {
                    // "Tất cả" - clear and close
                    dropdown.remove();
                }
                this._hlvApplyReceiptFilter(item.value);
                if (item.value !== '') {
                    // Refresh dropdown to show updated checkboxes
                    dropdown.remove();
                    this._hlvShowReceiptFilterDropdown(triggerBtn);
                }
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

        if (!value) {
            // Clear all receipt status filters
            _hlvActiveFilters.receiptStatus = [];
            console.log('[HLV] Cleared receipt filter');
        } else {
            // Toggle: if already exists, remove it; otherwise add it
            const existingIndex = _hlvActiveFilters.receiptStatus.findIndex(f => f.value === value);
            if (existingIndex >= 0) {
                // Remove existing
                _hlvActiveFilters.receiptStatus.splice(existingIndex, 1);
                console.log('[HLV] Removed receipt status:', value);
            } else {
                // Add new
                const domain = [['receipt_status', '=', value]];
                const label = getReceiptStatusLabel(value);
                _hlvActiveFilters.receiptStatus.push({ value: value, label: label, domain: domain });
                console.log('[HLV] Added receipt status:', value);
            }
        }

        // Apply combined filters
        applyHlvCombinedFilters(searchModel);
    }
});
