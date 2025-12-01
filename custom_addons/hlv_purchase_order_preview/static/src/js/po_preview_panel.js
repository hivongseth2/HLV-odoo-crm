/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { ListController } from "@web/views/list/list_controller";
import { onMounted, onPatched } from "@odoo/owl";

// Store reference to current controller for use in ListRenderer
let _hlvCurrentController = null;

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
 * Get current product filter value from searchModel
 */
function getProductFilterValue(searchModel) {
    if (!searchModel) return null;
    const items = searchModel.searchItems || {};
    for (const item of Object.values(items)) {
        if (item.description && item.description.startsWith('SP:')) {
            return item.description.substring(4); // Remove 'SP: ' prefix
        }
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
        // Sync product input with current searchModel state
        const productInput = document.querySelector('.hlv-product-search');
        const clearBtn = document.querySelector('.hlv-clear-product');
        if (!productInput) return;

        const currentValue = getProductFilterValue(this.env?.searchModel);

        if (productInput.value !== (currentValue || '')) {
            productInput.value = currentValue || '';
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

        // Get current filter value from searchModel
        const currentValue = getProductFilterValue(this.env?.searchModel) || '';

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

        // Get currently selected products
        const existingFilters = searchModel.searchItems || {};
        const selectedProducts = new Set();
        const filterIdsToRemove = [];

        for (const [id, item] of Object.entries(existingFilters)) {
            if (item.description && item.description.startsWith('SP:')) {
                filterIdsToRemove.push(id);

                // Extract product names from description (handle " hoặc " for multiple products)
                const productNames = item.description.substring(4).split(' hoặc ').map(s => s.trim());
                productNames.forEach(name => selectedProducts.add(name));
            }
        }

        // Remove all existing product filters
        filterIdsToRemove.forEach(id => searchModel.deactivateGroup(id));

        if (!value) {
            console.log('[HLV] Cleared all product search filters');
            return;
        }

        // Toggle the selected product
        if (selectedProducts.has(value)) {
            selectedProducts.delete(value);
        } else {
            selectedProducts.add(value);
        }

        if (selectedProducts.size === 0) {
            console.log('[HLV] No product filters selected');
            return;
        }

        // Build OR domain for multiple products
        const productArray = Array.from(selectedProducts);
        let domain;
        let description;

        if (productArray.length === 1) {
            domain = [
                '|',
                ['order_line.product_id.name', 'ilike', `%${productArray[0]}%`],
                ['order_line.product_id.default_code', 'ilike', `%${productArray[0]}%`]
            ];
            description = `SP: ${productArray[0]}`;
        } else {
            // Build OR domain for multiple products
            // Structure: ['|', ['|', cond1, cond2], ['|', cond3, cond4]]
            domain = [];

            // Add OR operators
            for (let i = 0; i < productArray.length - 1; i++) {
                domain.push('|');
            }

            // Add conditions for each product (name OR code)
            productArray.forEach(product => {
                domain.push(
                    '|',
                    ['order_line.product_id.name', 'ilike', `%${product}%`],
                    ['order_line.product_id.default_code', 'ilike', `%${product}%`]
                );
            });

            description = `SP: ${productArray.join(' hoặc ')}`;
        }

        try {
            searchModel.createNewFilters([{
                description: description,
                domain: domain,
                type: 'filter',
            }]);
            console.log('[HLV] Applied product search with facet (OR logic)');
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

        // Get currently selected suppliers
        const existingFilters = searchModel.searchItems || {};
        const selectedSuppliers = new Map(); // Map<supplierName, matchingIds>
        const filterIdsToRemove = [];

        console.log('[HLV] Existing filters:', existingFilters);

        for (const [id, item] of Object.entries(existingFilters)) {
            if (item.description && item.description.startsWith('NCC:')) {
                filterIdsToRemove.push(id);
                console.log('[HLV] Found NCC filter to remove:', id, item.description);

                // Extract supplier names from description
                const supplierNames = item.description.substring(5).split(' hoặc ').map(s => s.trim());

                // Extract IDs from domain (handle array-like objects recursively)
                let domainArray = null;
                if (item.domain) {
                    if (Array.isArray(item.domain)) {
                        domainArray = item.domain;
                    } else if (typeof item.domain === 'object' && item.domain.length !== undefined) {
                        domainArray = Array.from(item.domain);
                        console.log('[HLV] Converted supplier domain to array, length:', domainArray.length);
                    }
                }

                if (domainArray && domainArray.length > 0) {
                    // Convert nested array-like objects
                    for (let i = 0; i < domainArray.length; i++) {
                        const d = domainArray[i];
                        if (d && typeof d === 'object' && d.length !== undefined && !Array.isArray(d)) {
                            domainArray[i] = Array.from(d);
                            console.log('[HLV] Converted nested domain item:', domainArray[i]);
                        }
                    }

                    const idCondition = domainArray.find(d => Array.isArray(d) && d[0] === 'id' && d[1] === 'in');
                    if (idCondition && idCondition[2]) {
                        const allIds = idCondition[2];
                        // If multiple suppliers, we need to re-fetch each supplier's IDs
                        // For now, just store the combined IDs under the full description
                        if (supplierNames.length === 1) {
                            selectedSuppliers.set(supplierNames[0], allIds);
                        } else {
                            // Multiple suppliers - need to store them separately
                            // But we don't have individual IDs, so we'll fetch them again
                            supplierNames.forEach(name => {
                                selectedSuppliers.set(name, []); // Mark for re-fetch
                            });
                        }
                    }
                }
            }
        }

        // Remove all existing supplier filters
        filterIdsToRemove.forEach(id => searchModel.deactivateGroup(id));

        if (!value) {
            console.log('[HLV] Cleared all supplier search filters');
            return;
        }

        // Re-fetch IDs for suppliers that need it (marked with empty array)
        const orm = controller.env.services.orm;
        for (const [name, ids] of selectedSuppliers.entries()) {
            if (ids.length === 0) {
                try {
                    const matchingIds = await orm.call(
                        'purchase.order',
                        'search_supplier_exact',
                        [name, null]
                    );
                    selectedSuppliers.set(name, matchingIds);
                } catch (e) {
                    console.error('[HLV] Failed to re-fetch supplier IDs:', e);
                }
            }
        }

        // Toggle the selected supplier
        if (selectedSuppliers.has(value)) {
            selectedSuppliers.delete(value);
        } else {
            // Fetch IDs for the new supplier
            try {
                const matchingIds = await orm.call(
                    'purchase.order',
                    'search_supplier_exact',
                    [value, null]
                );
                console.log('[HLV] Supplier search found IDs:', matchingIds);

                if (matchingIds.length > 0) {
                    selectedSuppliers.set(value, matchingIds);
                } else {
                    console.warn('[HLV] No purchase orders found for supplier:', value);
                    return;
                }
            } catch (e) {
                console.error('[HLV] Failed to search supplier:', e);
                return;
            }
        }

        if (selectedSuppliers.size === 0) {
            console.log('[HLV] No supplier filters selected');
            return;
        }

        // Build OR domain for multiple suppliers
        const supplierArray = Array.from(selectedSuppliers.entries());
        let domain;
        let description;

        if (supplierArray.length === 1) {
            const [name, ids] = supplierArray[0];
            domain = [['id', 'in', ids]];
            description = `NCC: ${name}`;
        } else {
            // Merge all IDs and create single domain
            const allIds = new Set();
            supplierArray.forEach(([_, ids]) => {
                ids.forEach(id => allIds.add(id));
            });

            domain = [['id', 'in', Array.from(allIds)]];
            const names = supplierArray.map(([name, _]) => name).join(' hoặc ');
            description = `NCC: ${names}`;
        }

        try {
            searchModel.createNewFilters([{
                description: description,
                domain: domain,
                type: 'filter',
            }]);
            console.log('[HLV] Applied supplier filter (OR logic)');
        } catch (e) {
            console.error('[HLV] Failed to create supplier filter:', e);
        }
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

        // Get currently selected receipt statuses
        const existingFilters = searchModel.searchItems || {};
        const selectedStatuses = new Set();
        const filterIdsToRemove = [];

        console.log('[HLV] Checking existing filters for receipt status');

        for (const [id, item] of Object.entries(existingFilters)) {
            const desc = item.description;
            console.log('[HLV] Filter:', id, desc, 'domain type:', typeof item.domain, item.domain);

            // Check if this is a receipt status filter by examining the domain
            let isReceiptFilter = false;
            let domainArray = null;

            // Convert domain to array if it's array-like object
            if (item.domain) {
                if (Array.isArray(item.domain)) {
                    domainArray = item.domain;
                } else if (typeof item.domain === 'object' && item.domain.length !== undefined) {
                    // Array-like object, convert to real array recursively
                    domainArray = Array.from(item.domain);
                    console.log('[HLV] Converted array-like domain to array, length:', domainArray.length);
                }
            }

            if (domainArray && domainArray.length > 0) {
                console.log('[HLV] Checking domain items...');
                for (let i = 0; i < domainArray.length; i++) {
                    const d = domainArray[i];
                    console.log('[HLV] Domain item', i, ':', typeof d, d);

                    // Convert nested array-like objects to real arrays
                    if (d && typeof d === 'object' && d.length !== undefined && !Array.isArray(d)) {
                        domainArray[i] = Array.from(d);
                        console.log('[HLV] Converted nested array-like to array:', domainArray[i]);
                    }

                    const domainItem = Array.isArray(domainArray[i]) ? domainArray[i] : domainArray[i];
                    if (Array.isArray(domainItem) && domainItem[0] === 'receipt_status') {
                        isReceiptFilter = true;
                        console.log('[HLV] Found receipt_status in domain');
                        break;
                    }
                }
            }

            if (isReceiptFilter) {
                filterIdsToRemove.push(id);
                console.log('[HLV] Found receipt filter to remove:', id, desc);

                // Extract status values from domain
                domainArray.forEach(d => {
                    // Convert if needed
                    const domainItem = (d && typeof d === 'object' && d.length !== undefined && !Array.isArray(d))
                        ? Array.from(d)
                        : d;

                    if (Array.isArray(domainItem) && domainItem[0] === 'receipt_status' && domainItem[1] === '=' && domainItem[2]) {
                        selectedStatuses.add(domainItem[2]);
                        console.log('[HLV] Extracted status:', domainItem[2]);
                    }
                });
            }
        }

        console.log('[HLV] Selected statuses before toggle:', Array.from(selectedStatuses));

        // Remove all existing receipt filters
        filterIdsToRemove.forEach(id => searchModel.deactivateGroup(id));

        if (!value) {
            console.log('[HLV] Cleared all receipt filters');
            return;
        }

        // Toggle the selected status
        if (selectedStatuses.has(value)) {
            selectedStatuses.delete(value);
        } else {
            selectedStatuses.add(value);
        }

        if (selectedStatuses.size === 0) {
            console.log('[HLV] No receipt filters selected');
            return;
        }

        // Build OR domain for multiple statuses
        const statusArray = Array.from(selectedStatuses);
        let domain;
        let description;

        if (statusArray.length === 1) {
            domain = [['receipt_status', '=', statusArray[0]]];
            description = `TT: ${getReceiptStatusLabel(statusArray[0])}`;
        } else {
            // Build OR domain: ['|', ['status', '=', 'pending'], ['status', '=', 'partial']]
            domain = [];
            for (let i = 0; i < statusArray.length - 1; i++) {
                domain.push('|');
            }
            statusArray.forEach(status => {
                domain.push(['receipt_status', '=', status]);
            });

            const labels = statusArray.map(s => getReceiptStatusLabel(s)).join(' hoặc ');
            description = `TT: ${labels}`;
        }

        try {
            searchModel.createNewFilters([{
                description: description,
                domain: domain,
                type: 'filter',
            }]);
            console.log('[HLV] Applied receipt status filter (OR logic):', statusArray);
        } catch (e) {
            console.error('[HLV] Failed to create receipt filter:', e);
        }
    }
});
