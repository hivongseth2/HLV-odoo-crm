/** @odoo-module **/
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { onMounted, onPatched, useEffect } from "@odoo/owl";

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
 * Register the purchase order preview panel action
 */
registry.category("actions").add("hlv_po_preview_panel", async (env, action) => {
    const t0 = performance.now();
    const log = (...args) => console.log("[HLV][PO Preview]", ...args);
    const warn = (...args) => console.warn("[HLV][PO Preview]", ...args);
    const err = (...args) => console.error("[HLV][PO Preview]", ...args);

    log("start", { action });

    const orm = env.services.orm;
    const notify = env.services.notification;

    // Get resource ID from context
    const ctx = action?.context || {};
    const resId =
        action?.params?.res_id ??
        ctx.active_id ??
        (Array.isArray(ctx.active_ids) && ctx.active_ids.length ? ctx.active_ids[0] : undefined);

    log("ctx", ctx, "resId", resId);

    if (!resId) {
        notify.add("Không xác định được đơn mua hàng để xem nhanh.", { type: "warning" });
        return { destroy() { } };
    }

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
        try { target.remove(); } catch { }
    };
    target.querySelector(".hlv-close")?.addEventListener("click", destroy);

    // Close on Escape key
    const handleEscape = (e) => {
        if (e.key === 'Escape') {
            destroy();
            document.removeEventListener('keydown', handleEscape);
        }
    };
    document.addEventListener('keydown', handleEscape);

    try {
        const t1 = performance.now();
        log("RPC read(purchase.order) ->", resId);

        // Fetch purchase order data
        const [order] = await orm.read(
            "purchase.order",
            [resId],
            ["name", "partner_id", "state", "amount_total", "invoice_status", "receipt_status", "date_order"]
        );
        log("read OK", { ms: Math.round(performance.now() - t1), order });

        const t2 = performance.now();
        log("RPC search_read(purchase.order.line)");

        // Fetch order lines
        const lines = await orm.searchRead(
            "purchase.order.line",
            [["order_id", "=", resId]],
            ["product_id", "name", "product_qty", "qty_received", "price_unit", "price_subtotal", "product_uom"]
        );
        log("searchRead OK", { ms: Math.round(performance.now() - t2), count: lines?.length });

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

        log("rendered", { totalMs: Math.round(performance.now() - t0) });

        // Close action properly
        await env.services.action.doAction({ type: "ir.actions.act_window_close" });
        return { destroy };

    } catch (e) {
        err("exception", e);
        notify.add("Không thể tải dữ liệu đơn mua hàng.", { type: "danger" });
        try { target?.remove(); } catch { }

        await env.services.action.doAction({ type: "ir.actions.act_window_close" });
        return { destroy };
    }
});


/**
 * Patch ListRenderer to add filter dropdown on status columns for purchase.order
 */
patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);

        // Only apply to purchase.order model
        if (this.props.list?.resModel === 'purchase.order') {
            onMounted(() => this._hlvAddStatusFilters());
            onPatched(() => this._hlvAddStatusFilters());
        }
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

            // Create dropdown wrapper
            const wrapper = document.createElement('div');
            wrapper.className = 'hlv-status-filter-wrapper dropdown d-inline-block';
            wrapper.innerHTML = `
                <button class="btn btn-link p-0 dropdown-toggle hlv-filter-btn"
                        type="button"
                        data-bs-toggle="dropdown"
                        aria-expanded="false"
                        title="Nhấn để lọc theo trạng thái">
                    <i class="fa fa-filter"></i>
                </button>
                <ul class="dropdown-menu dropdown-menu-end">
                    <li><a class="dropdown-item" href="#" data-filter-name="${isInvoiceStatus ? 'filter_invoice_no' : 'filter_receipt_pending'}">
                        ${isInvoiceStatus ? 'Chưa lập hóa đơn' : 'Chờ nhận hàng'}
                    </a></li>
                    <li><a class="dropdown-item" href="#" data-filter-name="${isInvoiceStatus ? 'filter_invoice_to_invoice' : 'filter_receipt_partial'}">
                        ${isInvoiceStatus ? 'Cần lập hóa đơn' : 'Nhận một phần'}
                    </a></li>
                    <li><a class="dropdown-item" href="#" data-filter-name="${isInvoiceStatus ? 'filter_invoice_invoiced' : 'filter_receipt_full'}">
                        ${isInvoiceStatus ? 'Đã lập hóa đơn' : 'Đã nhận đủ'}
                    </a></li>
                </ul>
            `;

            // Add click handler for filter items
            wrapper.querySelectorAll('.dropdown-item').forEach(item => {
                item.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const filterName = item.dataset.filterName;
                    this._hlvApplyFilter(filterName);
                });
            });

            // Append to header cell
            th.style.position = 'relative';
            th.appendChild(wrapper);
        });
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
