/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { ListController } from "@web/views/list/list_controller";
import { onMounted, onPatched } from "@odoo/owl";

// Store reference to current controller's searchModel for use in ListRenderer
let _hlvCurrentSearchModel = null;

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
 * Get invoice status label in Vietnamese
 */
function getInvoiceStatusLabel(status) {
    const labels = {
        'no': 'Chưa lập hóa đơn',
        'to invoice': 'Cần lập hóa đơn',
        'invoiced': 'Đã lập hóa đơn'
    };
    return labels[status] || status || '';
}

/**
 * Get receipt status label in Vietnamese
 */
function getReceiptStatusLabel(status) {
    const labels = {
        'pending': 'Chờ nhận hàng',
        'partial': 'Nhận một phần',
        'full': 'Đã nhận đủ'
    };
    return labels[status] || status || '';
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
            ["name", "partner_id", "state", "amount_total", "invoice_status", "receipt_status", "date_order"]
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
        const orderDate = order?.date_order ? new Date(order.date_order).toLocaleDateString('vi-VN') : '';
        const invoiceStatusLabel = getInvoiceStatusLabel(order?.invoice_status);
        const receiptStatusLabel = getReceiptStatusLabel(order?.receipt_status);

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
                <div class="col-md-4">
                    <small class="text-muted">Ngày đặt hàng:</small>
                    <div>${orderDate}</div>
                </div>
                <div class="col-md-4">
                    <small class="text-muted">Trạng thái thanh toán:</small>
                    <div><span class="badge bg-info">${invoiceStatusLabel}</span></div>
                </div>
                <div class="col-md-4">
                    <small class="text-muted">Trạng thái nhập kho:</small>
                    <div><span class="badge bg-primary">${receiptStatusLabel}</span></div>
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
 * In Odoo 18, row.dataset.id contains datapoint ID, not database ID
 */
function getResIdFromRow(listRenderer, row) {
    const datapointId = row.dataset.id;
    if (!datapointId) return null;

    // Try to find record from ListRenderer's records
    const records = listRenderer.props.list?.records || [];
    for (const record of records) {
        if (record.id === datapointId) {
            return record.resId;
        }
    }

    // Fallback: try parsing as integer if it looks like a number
    const parsed = parseInt(datapointId);
    if (!isNaN(parsed) && parsed > 0) {
        return parsed;
    }

    return null;
}

/**
 * Patch ListController to add custom search bar for purchase.order
 */
patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);

        if (this.props.resModel === 'purchase.order') {
            // Store searchModel reference for ListRenderer to use
            _hlvCurrentSearchModel = this.env.searchModel;

            onMounted(() => {
                this._hlvAddCustomSearchBar();
            });
            onPatched(() => {
                this._hlvAddCustomSearchBar();
            });
        }
    },

    _hlvAddCustomSearchBar() {
        if (this.props.resModel !== 'purchase.order') return;

        // Find the control panel area
        const controlPanel = document.querySelector('.o_control_panel');
        if (!controlPanel) return;

        // Check if already added
        if (document.querySelector('.hlv-custom-search-bar')) return;

        // Find the breadcrumb/title area or search area
        const searchArea = controlPanel.querySelector('.o_searchview') ||
                          controlPanel.querySelector('.o_control_panel_main');
        if (!searchArea) return;

        // Create custom search bar - only product search
        const searchBar = document.createElement('div');
        searchBar.className = 'hlv-custom-search-bar d-flex gap-2 align-items-center ms-3';
        searchBar.innerHTML = `
            <div class="hlv-search-group d-flex align-items-center">
                <label class="hlv-search-label me-1" style="font-weight: 500; color: #714B67;">SP:</label>
                <input type="text" class="form-control form-control-sm hlv-product-search"
                       placeholder="Tìm sản phẩm trong đơn..." style="width: 180px;">
            </div>
        `;

        // Insert before search view or append to control panel
        const parentEl = searchArea.parentElement;
        if (parentEl) {
            parentEl.insertBefore(searchBar, searchArea);
        }

        // Add event listener for product search
        const productInput = searchBar.querySelector('.hlv-product-search');

        productInput?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this._hlvSearchByProduct(productInput.value.trim());
            }
        });
    },

    async _hlvSearchByProduct(value) {
        const searchModel = this.env?.searchModel;

        if (!searchModel) {
            console.warn('[HLV] SearchModel not available');
            return;
        }

        // FIXED: Always use setDomainParts - no fallback to doAction
        if (searchModel.setDomainParts) {
            searchModel.setDomainParts({
                hlv_product_search: value ? {
                    domain: [
                        '|',
                        ['order_line.product_id.name', 'ilike', value],
                        ['order_line.product_id.default_code', 'ilike', value]
                    ],
                    facetLabel: `SP: ${value}`,
                } : null
            });
        } else {
            console.error('[HLV] setDomainParts not available on searchModel');
        }
    }
});

/**
 * Patch ListRenderer to add preview button and filter dropdown for purchase.order
 */
patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);

        // Only apply to purchase.order model
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

        // Find all rows and add preview button
        const rows = tableEl.querySelectorAll('tbody tr.o_data_row');
        rows.forEach(row => {
            // Skip if already processed
            if (row.dataset.hlvPreviewAdded) return;
            row.dataset.hlvPreviewAdded = 'true';

            // Get record resId from the row using ListRenderer's records
            const resId = getResIdFromRow(this, row);
            if (!resId) {
                console.warn('[HLV] Could not get resId for row:', row.dataset.id);
                return;
            }

            // Find the last td or create button in last column
            const lastTd = row.querySelector('td:last-child');
            if (!lastTd) return;

            // Check if there's already our button
            if (lastTd.querySelector('.hlv-preview-btn')) return;

            // Create preview button
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

        // Find partner_id column header
        const partnerHeader = tableEl.querySelector('th[data-name="partner_id"]');
        if (!partnerHeader || partnerHeader.dataset.hlvSearchAdded) return;
        partnerHeader.dataset.hlvSearchAdded = 'true';

        // Create search button
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
        // Remove any existing popups
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

        // Close on click outside
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
        const searchModel = _hlvCurrentSearchModel || this.env?.searchModel;

        if (!searchModel) {
            console.warn('[HLV] SearchModel not available');
            return;
        }

        // FIXED: Only use setDomainParts - no doAction fallback
        if (searchModel.setDomainParts) {
            searchModel.setDomainParts({
                hlv_supplier_search: value ? {
                    domain: [['partner_id', 'ilike', value]],
                    facetLabel: `NCC: ${value}`,
                } : null
            });
        } else {
            console.error('[HLV] setDomainParts not available on searchModel');
        }
    },

    _hlvAddReceiptStatusFilter() {
        if (this.props.list?.resModel !== 'purchase.order') return;

        const tableEl = this.tableRef?.el;
        if (!tableEl) return;

        // Only add filter to receipt_status column (not invoice_status)
        const receiptHeader = tableEl.querySelector('th[data-name="receipt_status"]');
        if (!receiptHeader || receiptHeader.dataset.hlvFilterAdded) return;
        receiptHeader.dataset.hlvFilterAdded = 'true';

        // Create filter button
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
        // Remove any existing dropdown
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
            { value: 'pending', label: 'Chờ nhận hàng' },
            { value: 'partial', label: 'Nhận một phần' },
            { value: 'full', label: 'Đã nhận đủ' },
            { value: '', label: '— Tất cả —' }
        ];

        items.forEach((item, idx) => {
            const div = document.createElement('div');
            div.className = 'hlv-filter-dropdown-item';
            div.textContent = item.label;
            div.style.cssText = `
                padding: 10px 16px;
                cursor: pointer;
                font-size: 0.9rem;
                color: ${item.value === '' ? '#714B67' : '#333'};
                font-weight: ${item.value === '' ? '600' : '400'};
                border-bottom: ${idx < items.length - 1 ? '1px solid #f0f0f0' : 'none'};
                transition: background-color 0.15s;
            `;
            div.addEventListener('mouseenter', () => {
                div.style.backgroundColor = '#f8f4f7';
                div.style.color = '#714B67';
            });
            div.addEventListener('mouseleave', () => {
                div.style.backgroundColor = '';
                div.style.color = item.value === '' ? '#714B67' : '#333';
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

        // Close handlers
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
        const searchModel = _hlvCurrentSearchModel || this.env?.searchModel;

        if (!searchModel) {
            console.warn('[HLV] SearchModel not available');
            return;
        }

        // FIXED: Only use setDomainParts - no doAction fallback
        if (searchModel.setDomainParts) {
            searchModel.setDomainParts({
                hlv_receipt_filter: value ? {
                    domain: [['receipt_status', '=', value]],
                    facetLabel: getReceiptStatusLabel(value),
                } : null
            });
            console.log('[HLV] Applied filter via setDomainParts:', value);
        } else {
            console.error('[HLV] setDomainParts not available on searchModel');
        }
    }
});