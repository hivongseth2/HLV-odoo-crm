/** @odoo-module **/
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { onMounted, onPatched } from "@odoo/owl";

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
 * Patch ListRenderer to add preview button and filter dropdown for purchase.order
 */
patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);

        // Only apply to purchase.order model
        if (this.props.list?.resModel === 'purchase.order') {
            onMounted(() => {
                this._hlvAddStatusFilters();
                this._hlvAddPreviewButtons();
            });
            onPatched(() => {
                this._hlvAddStatusFilters();
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

    _hlvAddStatusFilters() {
        if (this.props.list?.resModel !== 'purchase.order') return;

        const tableEl = this.tableRef?.el;
        if (!tableEl) return;

        // Find invoice_status and receipt_status column headers
        const headers = tableEl.querySelectorAll('th[data-name="invoice_status"], th[data-name="receipt_status"]');

        headers.forEach(th => {
            // Skip if already processed
            if (th.dataset.hlvFilterAdded) return;
            th.dataset.hlvFilterAdded = 'true';

            const fieldName = th.dataset.name;
            const isInvoiceStatus = fieldName === 'invoice_status';

            // Create filter button (icon only)
            const filterBtn = document.createElement('button');
            filterBtn.className = 'btn btn-link p-0 hlv-filter-btn ms-1';
            filterBtn.type = 'button';
            filterBtn.title = 'Nhấn để lọc theo trạng thái';
            filterBtn.innerHTML = '<i class="fa fa-filter"></i>';

            // Store reference for dropdown positioning
            filterBtn.dataset.hlvField = fieldName;

            filterBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this._hlvShowFilterDropdown(filterBtn, isInvoiceStatus);
            });

            th.appendChild(filterBtn);
        });
    },

    _hlvShowFilterDropdown(triggerBtn, isInvoiceStatus) {
        // Remove any existing dropdown
        document.querySelectorAll('.hlv-filter-dropdown-portal').forEach(d => d.remove());

        // Get button position
        const rect = triggerBtn.getBoundingClientRect();

        // Create dropdown in body (portal pattern)
        const dropdown = document.createElement('div');
        dropdown.className = 'hlv-filter-dropdown-portal';
        dropdown.style.cssText = `
            position: fixed;
            top: ${rect.bottom + 4}px;
            left: ${rect.left}px;
            min-width: 180px;
            background: #fff;
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
            z-index: 10000;
            overflow: hidden;
        `;

        const items = isInvoiceStatus ? [
            { name: 'filter_invoice_no', label: 'Chưa lập hóa đơn' },
            { name: 'filter_invoice_to_invoice', label: 'Cần lập hóa đơn' },
            { name: 'filter_invoice_invoiced', label: 'Đã lập hóa đơn đầy đủ' }
        ] : [
            { name: 'filter_receipt_pending', label: 'Chờ nhận hàng' },
            { name: 'filter_receipt_partial', label: 'Nhận một phần' },
            { name: 'filter_receipt_full', label: 'Đã nhận đủ' }
        ];

        items.forEach((item, idx) => {
            const div = document.createElement('div');
            div.className = 'hlv-filter-dropdown-item';
            div.textContent = item.label;
            div.style.cssText = `
                padding: 10px 16px;
                cursor: pointer;
                font-size: 0.9rem;
                color: #333;
                border-bottom: ${idx < items.length - 1 ? '1px solid #f0f0f0' : 'none'};
                transition: background-color 0.15s;
            `;
            div.addEventListener('mouseenter', () => {
                div.style.backgroundColor = '#f8f4f7';
                div.style.color = '#714B67';
            });
            div.addEventListener('mouseleave', () => {
                div.style.backgroundColor = '';
                div.style.color = '#333';
            });
            div.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropdown.remove();
                this._hlvApplyFilter(item.name);
            });
            dropdown.appendChild(div);
        });

        document.body.appendChild(dropdown);

        // Close on click outside
        const closeHandler = (e) => {
            if (!dropdown.contains(e.target) && e.target !== triggerBtn) {
                dropdown.remove();
                document.removeEventListener('click', closeHandler);
            }
        };
        setTimeout(() => {
            document.addEventListener('click', closeHandler);
        }, 10);

        // Close on scroll
        const scrollHandler = () => {
            dropdown.remove();
            document.removeEventListener('scroll', scrollHandler, true);
        };
        document.addEventListener('scroll', scrollHandler, true);
    },

    _hlvApplyFilter(filterName) {
        // Get the search model from the controller
        const searchModel = this.env?.searchModel;
        if (!searchModel) {
            console.warn('[HLV] SearchModel not found');
            return;
        }

        // Find the filter by name and toggle it
        const searchItems = searchModel.getSearchItems((item) => item.name === filterName);
        if (searchItems.length > 0) {
            searchModel.toggleSearchItem(searchItems[0].id);
        } else {
            console.warn('[HLV] Filter not found:', filterName);
        }
    }
});
