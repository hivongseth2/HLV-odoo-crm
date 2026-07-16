/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { ListController } from "@web/views/list/list_controller";
import { onMounted, onPatched } from "@odoo/owl";

// Store reference to current controller
let _hlvCurrentController = null;

// Models to apply filters (bao gồm cả purchase.order)
const ENABLED_MODELS = [
    'purchase.order',
    'stock.picking',
    'sale.order',
    'hlv.undelivered.report',
    'out.return.report.line',
    'purchase.request',
];

function toUTCDateTime(dateStr, timeStr) {
    if (!dateStr) return null;
    const localDate = new Date(`${dateStr}T${timeStr}`);
    return localDate.toISOString().replace('T', ' ').split('.')[0];
}


// Config cho product search - model -> order line field và product field path
const PRODUCT_SEARCH_CONFIG = {
    'stock.picking': {
        lineField: 'move_ids',
        productPath: 'move_ids.product_id',
    },
    'sale.order': {
        lineField: 'order_line',
        productPath: 'order_line.product_id',
    },
    'purchase.order': {
        lineField: 'order_line',
        productPath: 'order_line.product_id',
    },
};

// Selection field options by model
const SELECTION_FIELDS = {
    'state': {
        'stock.picking': [
            { value: 'draft', label: 'Nháp', color: '#6c757d' },
            { value: 'waiting', label: 'Đang chờ hoạt động khác', color: '#ffc107' },
            { value: 'confirmed', label: 'Đang chờ', color: '#17a2b8' },
            { value: 'assigned', label: 'Sẵn sàng', color: '#28a745' },
            { value: 'done', label: 'Hoàn tất', color: '#714B67' },
            { value: 'cancel', label: 'Đã hủy', color: '#dc3545' },
        ],
        'hlv.undelivered.report': [
            { value: 'draft', label: 'Mới', color: '#6c757d' },
            { value: 'waiting', label: 'Chờ dịch chuyển khác', color: '#ffc107' },
            { value: 'confirmed', label: 'Đang chờ', color: '#17a2b8' },
            { value: 'assigned', label: 'Sẵn sàng', color: '#28a745' },
            { value: 'done', label: 'Hoàn thành', color: '#714B67' },
            { value: 'cancel', label: 'Đã hủy', color: '#dc3545' },
        ],
        'sale.order': [
            { value: 'draft', label: 'Báo giá', color: '#6c757d' },
            { value: 'sent', label: 'Báo giá đã gửi', color: '#17a2b8' },
            { value: 'sale', label: 'Đơn bán hàng', color: '#28a745' },
            { value: 'cancel', label: 'Đã hủy', color: '#dc3545' },
        ],
        'purchase.order': [
            { value: 'draft', label: 'RFQ', color: '#6c757d' },
            { value: 'sent', label: 'RFQ đã gửi', color: '#17a2b8' },
            { value: 'to approve', label: 'Cần phê duyệt', color: '#ffc107' },
            { value: 'purchase', label: 'Đơn mua hàng', color: '#28a745' },
            { value: 'done', label: 'Đã khoá', color: '#714B67' },
            { value: 'cancel', label: 'Đã hủy', color: '#dc3545' },
        ],
        'purchase.request': [
            { value: 'draft', label: 'Nháp', color: '#6c757d' },
            { value: 'to_approve', label: 'Cần phê duyệt', color: '#ffc107' },
            { value: 'approved', label: 'Đã duyệt', color: '#17a2b8' },
            { value: 'rejected', label: 'Từ chối', color: '#dc3545' },
            { value: 'done', label: 'Hoàn thành', color: '#28a745' },
        ],
    },
    'invoice_status': {
        'sale.order': [
            { value: 'upselling', label: 'Cơ hội Up-sell', color: '#17a2b8' },
            { value: 'invoiced', label: 'Đã thanh toán', color: '#28a745' },
            { value: 'to invoice', label: 'Cần thanh toán', color: '#ffc107' },
            { value: 'no', label: 'Không', color: '#6c757d' },
        ],
        'purchase.order': [
            { value: 'no', label: 'Không có gì để thanh toán', color: '#6c757d' },
            { value: 'to invoice', label: 'Chờ hoá đơn', color: '#ffc107' },
            { value: 'invoiced', label: 'Đã thanh toán hết', color: '#28a745' },
        ],
    },
    'delivery_status': {
        'sale.order': [
            { value: 'pending', label: 'Chưa giao', color: '#ffc107' },
            { value: 'started', label: 'Đã bắt đầu', color: '#17a2b8' },
            { value: 'partial', label: 'Đã giao một phần', color: '#fd7e14' },
            { value: 'full', label: 'Đã giao hết', color: '#28a745' },
        ],
    }
};

// Date field patterns
const DATE_FIELD_PATTERNS = [
    'date', 'datetime', 'scheduled', 'deadline', 'create_date', 'write_date',
    'date_order', 'date_planned', 'date_done', 'commitment_date', 'date_approve'
];

// Fields to exclude from filtering (non-stored, computed, or specific custom fields)
const EXCLUDED_FIELDS = [
    'activity_exception_decoration', 'message_needaction', // System fields
];

// Field Mapping for Non-Stored fields (Map displayed column -> Searchable db field(s))
const FIELD_MAPPING = {
    'stock.picking': {
        // Map 'Liên hệ' to both partner name and commercial partner name to match compute logic
        'x_studio_lin_h_1': ['partner_id.name', 'partner_id.commercial_partner_id.name'],
    }
};

/**
 * Format number as currency (Vietnamese locale)
 */
function fmtCurrency(value) {
    try {
        return new Intl.NumberFormat("vi-VN").format(value ?? 0);
    } catch {
        return String(value ?? "");
    }
}

// Badge Styles (Soft/High Contrast)
const BADGE_STYLES = {
    'success': 'background-color: #d1e7dd; color: #0f5132; border: 1px solid #badbcc;',
    'warning': 'background-color: #fff3cd; color: #664d03; border: 1px solid #ffecb5;',
    'danger': 'background-color: #f8d7da; color: #842029; border: 1px solid #f5c2c7;',
    'info': 'background-color: #cff4fc; color: #055160; border: 1px solid #b6effb;',
    'primary': 'background-color: #cfe2ff; color: #084298; border: 1px solid #b6d4fe;',
    'secondary': 'background-color: #e2e3e5; color: #41464b; border: 1px solid #d3d6d8;',
};

/**
 * Render badge HTML
 */
function renderBadge(status, label, styleKey = 'secondary') {
    const style = BADGE_STYLES[styleKey] || BADGE_STYLES['secondary'];
    return `<span class="badge" style="${style} padding: 0.35em 0.65em; font-size: 0.85em; font-weight: 500;">${label || status}</span>`;
}

/**
 * Configuration for Preview Panel
 */
const PREVIEW_CONFIG = {
    'purchase.order': {
        headerFields: ['name', 'partner_id', 'state', 'amount_total', 'date_planned', 'receipt_status'],
        lineModel: 'purchase.order.line',
        lineLinkField: 'order_id',
        lineFields: ['product_id', 'name', 'product_qty', 'qty_received', 'price_unit', 'price_subtotal', 'product_uom'],
        title: (d) => `${d.name || 'Đơn mua'} - ${d.partner_id?.[1] || ''}`,
        summary: [
            { label: 'Ngày dự kiến', value: (d) => d.date_planned ? new Date(d.date_planned).toLocaleDateString('vi-VN') : '' },
            {
                label: 'Trạng thái',
                value: (d) => {
                    const statusMap = { 'draft': 'Nháp', 'sent': 'Đã gửi', 'to approve': 'Chờ duyệt', 'purchase': 'Đơn hàng', 'done': 'Khóa', 'cancel': 'Đã hủy' };
                    const colorMap = { 'purchase': 'success', 'done': 'secondary', 'cancel': 'danger', 'draft': 'info', 'sent': 'primary', 'to approve': 'warning' };
                    return renderBadge(d.state, statusMap[d.state], colorMap[d.state] || 'primary')
                }
            },
            {
                label: 'Nhập kho',
                value: (d) => {
                    const map = { 'pending': 'Chưa nhận', 'partial': 'Một phần', 'full': 'Đã nhận hết' };
                    const color = { 'full': 'success', 'partial': 'warning', 'pending': 'secondary' };
                    return renderBadge(d.receipt_status, map[d.receipt_status], color[d.receipt_status]);
                }
            }
        ],
        columns: [
            { header: 'Sản phẩm', field: 'product_id', type: 'many2one', width: '35%' },
            { header: 'Mô tả', field: 'name', type: 'text', width: '25%' },
            { header: 'ĐVT', field: 'product_uom', type: 'many2one', align: 'center' },
            { header: 'SL đặt', field: 'product_qty', type: 'number', align: 'end' },
            { header: 'SL nhận', field: 'qty_received', type: 'number', align: 'end' },
            { header: 'Đơn giá', field: 'price_unit', type: 'currency', align: 'end' },
            { header: 'Thành tiền', field: 'price_subtotal', type: 'currency', align: 'end', bold: true },
        ],
        footer: (d) => `Mở rộng: Tổng tiền ${fmtCurrency(d.amount_total)}`
    },
    /*
    'sale.order': {
        headerFields: ['name', 'partner_id', 'state', 'amount_total', 'date_order', 'invoice_status'],
        lineModel: 'sale.order.line',
        lineLinkField: 'order_id',
        lineFields: ['product_id', 'name', 'product_uom_qty', 'qty_delivered', 'price_unit', 'price_subtotal', 'product_uom'],
        title: (d) => `${d.name || 'Đơn bán'} - ${d.partner_id?.[1] || ''}`,
        summary: [
            { label: 'Ngày đặt', value: (d) => d.date_order ? new Date(d.date_order).toLocaleDateString('vi-VN') : '' },
            {
                label: 'Trạng thái',
                value: (d) => {
                    const statusMap = { 'draft': 'Báo giá', 'sent': 'Đã gửi', 'sale': 'Đơn hàng', 'done': 'Khóa', 'cancel': 'Đã hủy' };
                    const colorMap = { 'sale': 'success', 'done': 'secondary', 'cancel': 'danger', 'draft': 'info', 'sent': 'primary' };
                    return renderBadge(d.state, statusMap[d.state], colorMap[d.state] || 'primary')
                }
            }
        ],
        columns: [
            { header: 'Sản phẩm', field: 'product_id', type: 'many2one', width: '35%' },
            { header: 'Mô tả', field: 'name', type: 'text', width: '25%' },
            { header: 'ĐVT', field: 'product_uom', type: 'many2one', align: 'center' },
            { header: 'SL đặt', field: 'product_uom_qty', type: 'number', align: 'end' },
            { header: 'SL giao', field: 'qty_delivered', type: 'number', align: 'end' },
            { header: 'Đơn giá', field: 'price_unit', type: 'currency', align: 'end' },
            { header: 'Thành tiền', field: 'price_subtotal', type: 'currency', align: 'end', bold: true },
        ],
        footer: (d) => `Tổng tiền: ${fmtCurrency(d.amount_total)}`
    },
    */
    'stock.picking': {
        headerFields: ['name', 'partner_id', 'state', 'scheduled_date', 'origin', 'picking_type_id'],
        lineModel: 'stock.move',
        lineLinkField: 'picking_id',
        lineFields: ['product_id', 'description_picking', 'product_uom_qty', 'quantity', 'product_uom'],
        title: (d) => `${d.name || 'Phiếu kho'} - ${d.picking_type_id?.[1] || ''}`,
        summary: [
            { label: 'Đối tác', value: (d) => d.partner_id?.[1] || '---' },
            { label: 'Nguồn', value: (d) => d.origin || '' },
            { label: 'Ngày dự kiến', value: (d) => d.scheduled_date ? new Date(d.scheduled_date).toLocaleDateString('vi-VN') : '' },
            {
                label: 'Trạng thái',
                value: (d) => {
                    const statusMap = { 'draft': 'Nháp', 'waiting': 'Đang chờ', 'confirmed': 'Chờ xử lý', 'assigned': 'Sẵn sàng', 'done': 'Hoàn thành', 'cancel': 'Đã hủy' };
                    const colorMap = { 'done': 'success', 'assigned': 'primary', 'confirmed': 'info', 'cancel': 'danger', 'waiting': 'warning', 'draft': 'secondary' };
                    return renderBadge(d.state, statusMap[d.state], colorMap[d.state] || 'secondary')
                }
            }
        ],
        columns: [
            { header: 'Sản phẩm', field: 'product_id', type: 'many2one', width: '40%' },
            { header: 'Mô tả', field: 'description_picking', type: 'text', width: '30%' },
            { header: 'ĐVT', field: 'product_uom', type: 'many2one', align: 'center' },
            { header: 'Nhu cầu', field: 'product_uom_qty', type: 'number', align: 'end' },
            { header: 'Hoàn tất', field: 'quantity', type: 'number', align: 'end', bold: true },
        ],
        footer: (d) => ''
    }
};

/**
 * Show Generic Preview Panel as an EXPANDABLE ROW
 */
async function showPreviewPanel(env, resModel, resId, triggerBtn) {
    const config = PREVIEW_CONFIG[resModel];
    if (!config) return;

    // Find the TR row
    const tr = triggerBtn.closest('tr');
    if (!tr) return;

    // Check if already open
    if (tr.classList.contains('hlv-preview-open')) {
        tr.classList.remove('hlv-preview-open');
        const nextRow = tr.nextElementSibling;
        if (nextRow && nextRow.classList.contains('hlv-preview-row')) {
            nextRow.remove();
        }
        return; // Toggle off
    }

    // Close other open previews if single-mode desired (optional, but good for cleanliness)
    document.querySelectorAll('.hlv-preview-open').forEach(row => {
        row.classList.remove('hlv-preview-open');
        const next = row.nextElementSibling;
        if (next && next.classList.contains('hlv-preview-row')) next.remove();
    });

    tr.classList.add('hlv-preview-open');

    // Create new TR
    const previewRow = document.createElement('tr');
    previewRow.className = 'hlv-preview-row';
    // No background on TR itself to let the div have shadow/margin

    // Count columns to colspan
    const colCount = tr.querySelectorAll('td').length;

    const cell = document.createElement('td');
    cell.colSpan = colCount;
    cell.style.padding = '0';
    cell.style.borderTop = 'none';
    cell.style.backgroundColor = 'transparent'; // Let the div handle background

    previewRow.appendChild(cell);

    // Insert after current row
    tr.parentNode.insertBefore(previewRow, tr.nextSibling);

    // Container for panel with ENHANCED    // Build container with enhanced styling and arrow
    const target = document.createElement("div");
    target.className = "hlv-preview-panel";
    target.style.cssText = `
        background: #fff;
        border: 1px solid #dcdcdc;
        border-left: 6px solid #714B67;
        box-shadow: 0 6px 12px -4px rgba(0,0,0,0.15);
        padding: 16px;
        margin: 10px 12px 12px 12px;
        position: relative;
        border-radius: 4px;
    `;

    // Add arrow styles (checked if exists to avoid duplication)
    if (!document.getElementById('hlv-preview-arrow-style')) {
        const style = document.createElement('style');
        style.id = 'hlv-preview-arrow-style';
        style.innerHTML = `
            .hlv-preview-panel::before {
                content: "";
                position: absolute;
                top: -10px;
                left: 20px;
                border-width: 0 10px 10px 10px;
                border-style: solid;
                border-color: transparent transparent #dcdcdc transparent;
                z-index: 0;
            }
            .hlv-preview-panel::after {
                content: "";
                position: absolute;
                top: -9px;
                left: 21px;
                border-width: 0 9px 9px 9px;
                border-style: solid;
                border-color: transparent transparent #fff transparent;
                z-index: 1;
            }
            .hlv-u-summary { display: flex; gap: 30px; margin-bottom: 20px; flex-wrap: wrap; padding-bottom: 16px; border-bottom: 1px solid #dee2e6; }
            .hlv-u-summary-item label { display: block; font-size: 0.75rem; color: #555; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.6px; font-weight: 700; }
            .hlv-u-summary-item div { font-weight: 500; font-size: 1rem; color: #222; }
            .table-preview th { background: #f8f9fa; font-size: 0.8rem; text-transform: uppercase; color: #555; font-weight: 700; border-bottom: 2px solid #dee2e6; padding: 10px 14px; }
            .table-preview td { font-size: 0.95rem; padding: 10px 14px; vertical-align: middle; border-bottom: 1px solid #f0f0f0; color: #333; }
            .table-preview tr:last-child td { border-bottom: none; }
            .hlv-u-title { font-weight: 700; color: #714B67; font-size: 1.1rem; }
        `;
        document.head.appendChild(style);
    }

    target.innerHTML += `
        <div class="hlv-u-header d-flex justify-content-between align-items-center mb-3">
            <h5 class="hlv-u-title m-0"><span class="fa fa-file-text-o me-2 opacity-50"></span>${config.title({})}</h5>
            <button class="btn btn-sm btn-outline-secondary hlv-close-preview rounded-circle p-1" style="width: 28px; height: 28px; line-height: 1;"><i class="fa fa-times"></i></button>
        </div>
        <div class="hlv-u-body">
            <div class="hlv-u-spinner text-center py-4"><span class="fa fa-circle-o-notch fa-spin fa-2x text-muted"></span></div>
        </div>
    `;

    cell.appendChild(target);

    // Close logic
    target.querySelector('.hlv-close-preview').addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation(); // Stop propagation
        tr.classList.remove('hlv-preview-open');
        previewRow.remove();
    });

    try {
        const orm = env.services.orm;
        // Fetch Header
        const [record] = await orm.read(resModel, [resId], config.headerFields);
        if (!record) throw new Error("Record not found");

        // Fetch Lines
        const lines = await orm.searchRead(
            config.lineModel,
            [[config.lineLinkField, '=', resId]],
            config.lineFields
        );

        // Render Content
        const titleEl = target.querySelector(".hlv-u-title");
        const bodyEl = target.querySelector(".hlv-u-body");

        // Update title to allow it to be dynamic based on record if needed (currently using empty obj in loading)
        // Re-render title correctly
        titleEl.innerHTML = `<span class="fa fa-file-text-o me-2"></span>${config.title(record)}`;

        // Render Summary
        const summaryHtml = config.summary.map(s => `
            <div class="hlv-u-summary-item">
                <label>${s.label}</label>
                <div>${s.value(record) || '---'}</div>
            </div>
        `).join('');

        // Render Table Headers
        const thHtml = config.columns.map(c => `
            <th class="${c.align ? 'text-' + c.align : 'text-start'}" style="${c.width ? 'width:' + c.width : ''}">${c.header}</th>
        `).join('');

        // Render Rows
        const rowsHtml = lines.map(line => {
            const tds = config.columns.map(c => {
                let text = '';
                const val = line[c.field];
                if (c.type === 'many2one') text = val?.[1] || '';
                else if (c.type === 'currency') text = fmtCurrency(val);
                else if (c.type === 'number') text = val || 0;
                else text = val || '';

                return `<td class="${c.align ? 'text-' + c.align : 'text-start'} ${c.bold ? 'fw-bold' : ''}">${text}</td>`;
            }).join('');
            return `<tr>${tds}</tr>`;
        }).join('');

        // Footer
        let footerHtml = '';
        if (config.footer) {
            const footerText = config.footer(record);
            if (footerText) {
                footerHtml = `
            <div class="mt-2 text-end fw-bold text-dark border-top pt-2">
                ${footerText}
            </div>
        `;
            }
        }

        bodyEl.innerHTML = `
            <div class="hlv-u-summary">${summaryHtml}</div>
            <div class="table-responsive bg-white border rounded">
                <table class="table table-preview w-100 mb-0">
                    <thead><tr>${thHtml}</tr></thead>
                    <tbody>${rowsHtml}</tbody>
                </table>
            </div>
            ${footerHtml}
        `;

    } catch (e) {
        console.error(e);
        target.querySelector(".hlv-u-body").innerHTML = `<div class="text-danger p-3">Lỗi tải dữ liệu: ${e.message}</div>`;
    }
}

/**
 * Detect if a field is a date type
 */
function isDateField(fieldName, headerEl) {
    const lowerName = fieldName.toLowerCase();
    if (DATE_FIELD_PATTERNS.some(p => lowerName.includes(p))) {
        return true;
    }
    if (headerEl) {
        const classList = headerEl.className || '';
        if (classList.includes('o_date') || classList.includes('datetime')) {
            return true;
        }
    }
    return false;
}

/**
 * Get selection options for a field
 */
function getSelectionOptions(fieldName, resModel) {
    return SELECTION_FIELDS[fieldName]?.[resModel] || null;
}

/**
 * Get field label from header element
 */
function getFieldLabel(headerEl) {
    const clone = headerEl.cloneNode(true);
    clone.querySelectorAll('button, .fa, .o_resize, .hlv-filter-btn').forEach(el => el.remove());
    return clone.textContent.trim() || 'Field';
}

/**
 * Patch ListController to store reference and add product search bar
 */
patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);
        if (ENABLED_MODELS.includes(this.props.resModel)) {
            _hlvCurrentController = this;

            onMounted(() => {
                this._hlvAddProductSearchBar();
            });
            onPatched(() => {
                this._hlvAddProductSearchBar();
            });
        }
    },

    /**
     * Add product search bar to control panel (same style as PO preview)
     */
    _hlvAddProductSearchBar() {
        if (!ENABLED_MODELS.includes(this.props.resModel)) return;

        const controlPanel = document.querySelector('.o_control_panel');
        if (!controlPanel) return;

        // Skip if already added
        if (document.querySelector('.hlv-product-search-bar')) return;

        const buttonsArea = controlPanel.querySelector('.o_control_panel_actions') ||
            controlPanel.querySelector('.o_cp_action_menus');
        const breadcrumbArea = controlPanel.querySelector('.o_control_panel_breadcrumbs');

        const searchBar = document.createElement('div');
        searchBar.className = 'hlv-product-search-bar d-flex gap-2 align-items-center';
        searchBar.style.cssText = 'margin-left: auto; margin-right: 16px;';

        searchBar.innerHTML = `
            <div class="hlv-search-group d-flex align-items-center">
                <label class="hlv-search-label me-2" style="font-weight: 500; color: #714B67; white-space: nowrap;">SP:</label>
                <input type="text" class="form-control form-control-sm hlv-product-input"
                       placeholder="Tìm sản phẩm..." style="width: 180px;">
            </div>
    `;

        if (buttonsArea && buttonsArea.parentElement) {
            buttonsArea.parentElement.insertBefore(searchBar, buttonsArea);
        } else if (breadcrumbArea && breadcrumbArea.parentElement) {
            breadcrumbArea.parentElement.appendChild(searchBar);
        } else {
            const mainArea = controlPanel.querySelector('.o_control_panel_main');
            if (mainArea) {
                mainArea.appendChild(searchBar);
            }
        }

        const productInput = searchBar.querySelector('.hlv-product-input');

        productInput?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                const value = productInput.value.trim();
                if (value) {
                    this._hlvSearchByProduct(value);
                    productInput.value = '';
                }
            }
        });
    },

    /**
     * Search by product in order lines
     */
    async _hlvSearchByProduct(value) {
        console.log('[HLV] Product search:', value);

        const resModel = this.props.resModel;
        const config = PRODUCT_SEARCH_CONFIG[resModel];
        if (!config) return;

        const searchModel = this.env.searchModel;
        if (!searchModel?.createNewFilters) {
            console.error('[HLV] SearchModel not available');
            return;
        }

        // Get currently selected products from ACTIVE filters
        const query = searchModel.query || [];
        const searchItems = searchModel.searchItems || {};
        const selectedProducts = new Set();
        const filterIdsToRemove = [];

        for (const queryItem of query) {
            const itemId = queryItem.searchItemId;
            const item = searchItems[itemId];

            if (item?.description?.startsWith('SP:')) {
                filterIdsToRemove.push(itemId);
                const productNames = item.description.substring(4).split(' hoặc ').map(s => s.trim());
                productNames.forEach(name => selectedProducts.add(name));
            }
        }

        // Remove existing product filters
        for (const id of filterIdsToRemove) {
            try {
                if (searchModel.toggleSearchItem) {
                    searchModel.toggleSearchItem(id);
                } else {
                    searchModel.deactivateGroup(id);
                }
            } catch (e) {
                console.error('[HLV] Failed to remove filter:', id, e);
            }
        }

        if (filterIdsToRemove.length > 0) {
            await new Promise(resolve => setTimeout(resolve, 50));
        }

        if (!value) return;

        // Toggle selected product
        if (selectedProducts.has(value)) {
            selectedProducts.delete(value);
        } else {
            selectedProducts.add(value);
        }

        if (selectedProducts.size === 0) return;

        // Build OR domain for products
        const productArray = Array.from(selectedProducts);
        let domain;
        let description;

        if (productArray.length === 1) {
            domain = [
                '|',
                [`${config.productPath}.name`, 'ilike', `%${productArray[0]}%`],
                [`${config.productPath}.default_code`, 'ilike', `%${productArray[0]}%`]
            ];
            description = `SP: ${productArray[0]}`;
        } else {
            domain = [];
            for (let i = 0; i < productArray.length - 1; i++) {
                domain.push('|');
            }
            productArray.forEach(product => {
                domain.push(
                    '|',
                    [`${config.productPath}.name`, 'ilike', `%${product}%`],
                    [`${config.productPath}.default_code`, 'ilike', `%${product}%`]
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
            console.log('[HLV] Applied product filter');
        } catch (e) {
            console.error('[HLV] Failed:', e);
        }
    },
});

/**
 * Patch ListRenderer to add universal column filters
 */
patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);

        const resModel = this.props.list?.resModel;
        if (resModel && ENABLED_MODELS.includes(resModel)) {
            onMounted(() => {
                this._hlvAddUniversalFilters();
                this._hlvAddPreviewButtons();
            });
            onPatched(() => {
                this._hlvAddUniversalFilters();
                this._hlvAddPreviewButtons();
            });
        }
    },

    /**
     * Add "Eye" preview buttons to rows
     */
    _hlvAddPreviewButtons() {
        const resModel = this.props.list?.resModel;
        if (!resModel || !PREVIEW_CONFIG[resModel]) return;

        const tableEl = this.tableRef?.el;
        if (!tableEl) return;

        // Try to find the helper function to get ID. 
        // Typically ListRenderer has access to props.list.records.
        // We iterate rows to find data-id.

        const rows = tableEl.querySelectorAll('tbody tr.o_data_row');
        rows.forEach(row => {
            if (row.dataset.hlvPreviewAdded) return;
            row.dataset.hlvPreviewAdded = 'true';

            // Find last cell to inject button
            const lastTd = row.querySelector('td:last-child');
            if (!lastTd) return;

            // Check if button already exists (redundant check but safe)
            if (lastTd.querySelector('.hlv-u-preview-btn')) return;

            // Get ResID
            // ListRenderer usually stores resId in the record object mapped to data-id
            // We need to find the record from props.
            const datapointId = row.dataset.id;
            const record = this.props.list?.records?.find(r => r.id === datapointId);
            const resId = record?.resId;

            if (!resId) return;

            const btn = document.createElement('button');
            btn.className = 'btn btn-sm hlv-u-preview-btn ms-1';
            btn.innerHTML = '<span class="fa fa-eye me-1"></span>Xem';
            btn.title = 'Xem nhanh';
            btn.type = 'button';
            // Style as a pill button for better visibility/interaction
            btn.style.cssText = `
                background-color: #eef2f7;
                color: #4c4c4c;
                border: 1px solid #dae0e5;
                border-radius: 12px;
                padding: 1px 10px;
                font-size: 0.8rem;
                font-weight: 500;
                transition: all 0.2s;
            `;
            btn.addEventListener('mouseenter', () => {
                btn.style.backgroundColor = '#714B67';
                btn.style.color = '#fff';
                btn.style.borderColor = '#714B67';
            });
            btn.addEventListener('mouseleave', () => {
                btn.style.backgroundColor = '#eef2f7';
                btn.style.color = '#4c4c4c';
                btn.style.borderColor = '#dae0e5';
            });

            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                // Pass btn as trigger
                showPreviewPanel(this.env, resModel, resId, btn);
            });

            // Prepend or append? Let's append to not mess up alignment if possible, same as Purchase.
            lastTd.appendChild(btn);
        });
    },

    /**
     * Add filter buttons to ALL column headers dynamically with NICER UI
     */
    _hlvAddUniversalFilters() {
        const resModel = this.props.list?.resModel;
        if (!resModel || !ENABLED_MODELS.includes(resModel)) return;

        const tableEl = this.tableRef?.el;
        if (!tableEl) return;

        const headers = tableEl.querySelectorAll('th[data-name]');

        headers.forEach(header => {
            const fieldName = header.dataset.name;
            if (!fieldName || fieldName === '__checkbox__') return;
            if (EXCLUDED_FIELDS.includes(fieldName)) return; // Skip excluded fields
            if (header.dataset.hlvFilterAdded) return;
            header.dataset.hlvFilterAdded = 'true';

            let filterType = 'text';
            let options = null;

            const selectionOptions = getSelectionOptions(fieldName, resModel);
            if (selectionOptions) {
                filterType = 'select';
                options = selectionOptions;
            } else if (isDateField(fieldName, header)) {
                filterType = 'date';
            }

            const label = getFieldLabel(header);

            // Redesigned Filter Button - Always Visible
            const filterBtn = document.createElement('span');
            filterBtn.className = 'hlv-filter-icon ms-1';
            filterBtn.innerHTML = '<i class="fa fa-filter"></i>';
            filterBtn.title = `Lọc theo ${label} `;

            // Inline CSS for the icon to look cleaner and permanent
            filterBtn.style.cssText = `
                cursor: pointer;
                opacity: 0.5;
                font-size: 0.85rem;
                margin-left: 6px;
                color: #555;
                transition: all 0.2s;
            `;

            // Just hover effects for color
            filterBtn.addEventListener('mouseenter', () => { filterBtn.style.opacity = '1'; filterBtn.style.color = '#714B67'; });
            filterBtn.addEventListener('mouseleave', () => { filterBtn.style.opacity = '0.5'; filterBtn.style.color = '#555'; });

            filterBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (filterType === 'select') {
                    this._hlvShowSelectDropdown(filterBtn, fieldName, label, options);
                } else if (filterType === 'date') {
                    this._hlvShowDateDropdown(filterBtn, fieldName, label);
                } else if (fieldName === 'x_studio_kho_nhn') {
                    this._hlvShowWarehouseFilterDropdown(filterBtn, label);
                } else {
                    this._hlvShowTextPopup(filterBtn, fieldName, label);
                }
            });

            header.appendChild(filterBtn);
        });
    },

    /**
     * Show text search popup
     */
    _hlvShowTextPopup(triggerBtn, fieldName, label) {
        document.querySelectorAll('.hlv-filter-dropdown-portal').forEach(d => d.remove());

        const rect = triggerBtn.getBoundingClientRect();

        const popup = document.createElement('div');
        popup.className = 'hlv-filter-dropdown-portal';
        popup.style.cssText = `
            position: fixed;
            top: ${rect.bottom + 4}px;
            left: ${Math.max(10, rect.left - 100)}px;
            min-width: 200px;
            background: #fff;
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
            z-index: 10000;
            padding: 10px;
        `;
        popup.innerHTML = `
            <input type="text" class="form-control form-control-sm hlv-popup-input"
                   placeholder="Nhập ${label}..." autofocus style="width: 100%;">
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
                if (value) this._hlvApplyTextFilter(fieldName, label, value);
            } else if (e.key === 'Escape') {
                popup.remove();
            }
        });

        this._hlvSetupPopupClose(popup, triggerBtn);
    },

    /**
     * Show select dropdown
     */
    _hlvShowSelectDropdown(triggerBtn, fieldName, label, options) {
        document.querySelectorAll('.hlv-filter-dropdown-portal').forEach(d => d.remove());

        const rect = triggerBtn.getBoundingClientRect();

        const dropdown = document.createElement('div');
        dropdown.className = 'hlv-filter-dropdown-portal';
        dropdown.style.cssText = `
            position: fixed;
            top: ${rect.bottom + 4}px;
            left: ${Math.max(10, rect.left - 80)}px;
            min-width: 160px;
            background: #fff;
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
            z-index: 10000;
            overflow: hidden;
        `;

        const allOptions = [...options, { value: '', label: '— Tất cả —', color: '#714B67' }];

        allOptions.forEach((item, idx) => {
            const div = document.createElement('div');
            div.className = 'hlv-filter-dropdown-item';

            const colorDot = item.color
                ? `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${item.color};margin-right:8px;"></span>`
                : '';

            div.innerHTML = colorDot + item.label;
            div.style.cssText = `
                padding: 10px 16px;
                cursor: pointer;
                font-size: 0.9rem;
                color: ${item.value === '' ? '#714B67' : '#333'};
                font-weight: ${item.value === '' ? '600' : '400'};
                border-bottom: ${idx < allOptions.length - 1 ? '1px solid #f0f0f0' : 'none'};
                transition: background-color 0.15s;
                display: flex;
                align-items: center;
            `;

            div.addEventListener('mouseenter', () => div.style.backgroundColor = '#f8f4f7');
            div.addEventListener('mouseleave', () => div.style.backgroundColor = '');
            div.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropdown.remove();
                this._hlvApplySelectFilter(fieldName, label, item.value, item.label);
            });

            dropdown.appendChild(div);
        });

        document.body.appendChild(dropdown);
        this._hlvSetupPopupClose(dropdown, triggerBtn);
    },

    /**
     * Show date range picker
     */
    _hlvShowDateDropdown(triggerBtn, fieldName, label) {
        document.querySelectorAll('.hlv-filter-dropdown-portal').forEach(d => d.remove());

        const rect = triggerBtn.getBoundingClientRect();

        const dropdown = document.createElement('div');
        dropdown.className = 'hlv-filter-dropdown-portal';
        dropdown.style.cssText = `
            position: fixed;
            top: ${rect.bottom + 4}px;
            left: ${Math.max(10, rect.left - 100)}px;
            min-width: 240px;
            background: #fff;
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
            z-index: 10000;
            padding: 12px;
        `;

        dropdown.innerHTML = `
            <div style="margin-bottom: 8px; font-weight: 500; color: #714B67;">${label}</div>
            <div style="margin-bottom: 8px;">
                <label style="font-size: 0.85rem; color: #666; margin-bottom: 4px; display: block;">Từ ngày:</label>
                <input type="date" class="form-control form-control-sm hlv-date-from" style="margin-bottom: 8px;">
            </div>
            <div style="margin-bottom: 8px;">
                <label style="font-size: 0.85rem; color: #666; margin-bottom: 4px; display: block;">Đến ngày:</label>
                <input type="date" class="form-control form-control-sm hlv-date-to" style="margin-bottom: 8px;">
            </div>
            <div style="display: flex; gap: 8px;">
                <button class="btn btn-sm btn-primary hlv-date-apply" style="flex: 1;">Áp dụng</button>
                <button class="btn btn-sm btn-secondary hlv-date-clear" style="flex: 1;">Xóa</button>
            </div>
        `;

        document.body.appendChild(dropdown);

        const applyBtn = dropdown.querySelector('.hlv-date-apply');
        const clearBtn = dropdown.querySelector('.hlv-date-clear');

        applyBtn.addEventListener('click', () => {
            const fromValue = dropdown.querySelector('.hlv-date-from').value;
            const toValue = dropdown.querySelector('.hlv-date-to').value;
            if (fromValue || toValue) {
                dropdown.remove();
                this._hlvApplyDateFilter(fieldName, label, fromValue, toValue);
            }
        });

        clearBtn.addEventListener('click', () => {
            dropdown.remove();
            this._hlvClearFilter(fieldName, label);
        });

        this._hlvSetupPopupClose(dropdown, triggerBtn);
    },

    /**
     * Setup popup close handlers
     */
    _hlvSetupPopupClose(popup, triggerBtn) {
        const closeHandler = (e) => {
            if (!popup.contains(e.target) && e.target !== triggerBtn) {
                popup.remove();
                document.removeEventListener('click', closeHandler);
            }
        };
        setTimeout(() => document.addEventListener('click', closeHandler), 10);

        const scrollHandler = () => {
            popup.remove();
            document.removeEventListener('scroll', scrollHandler, true);
        };
        document.addEventListener('scroll', scrollHandler, true);
    },

    /**
     * Apply text filter
     */
    async _hlvApplyTextFilter(fieldName, label, value) {
        console.log('[HLV Filter] Text:', fieldName, value);

        const controller = _hlvCurrentController;
        if (!controller) return;

        const resModel = controller.props.resModel;
        const mappedField = FIELD_MAPPING[resModel]?.[fieldName] || fieldName;

        const searchModel = controller.env.searchModel;
        if (!searchModel?.createNewFilters) return;

        // 1. Identify active filters for this field
        const query = searchModel.query || [];
        const searchItems = searchModel.searchItems || {};
        const activeValues = new Set();
        const filterIdsToRemove = [];

        for (const queryItem of query) {
            const itemId = queryItem.searchItemId;
            const item = searchItems[itemId];

            if (item && item.description && item.description.startsWith(`${label}: `)) {
                filterIdsToRemove.push(itemId);
                const domain = item.domain;
                if (domain) {
                    this._hlvExtractValuesFromDomain(domain, mappedField, activeValues);
                }
            }
        }

        // 2. Remove existing filters
        for (const id of filterIdsToRemove) {
            try {
                if (searchModel.toggleSearchItem) {
                    searchModel.toggleSearchItem(id);
                } else {
                    searchModel.deactivateGroup(id);
                }
            } catch (e) {
                console.error('[HLV Filter] Remove failed:', e);
            }
        }

        if (filterIdsToRemove.length > 0) {
            await new Promise(resolve => setTimeout(resolve, 50));
        }

        if (!value) {
            if (activeValues.size === 0) return;
        } else {
            // 3. Toggle the new value
            if (activeValues.has(value)) {
                activeValues.delete(value);
            } else {
                activeValues.add(value);
            }
        }

        if (activeValues.size === 0) return;

        // 4. Build new Domain
        const valueArray = Array.from(activeValues);
        const fields = Array.isArray(mappedField) ? mappedField : [mappedField];
        let newDomain;
        let newDescription;

        // Display description
        if (valueArray.length === 1) {
            newDescription = `${label}: ${valueArray[0]} `;
        } else {
            newDescription = `${label}: ${valueArray.join(' hoặc ')} `;
        }

        // Build all atomic conditions: for each Value, for each Field
        const conditions = [];
        valueArray.forEach(val => {
            fields.forEach(field => {
                conditions.push([field, 'ilike', val]);
            });
        });

        if (conditions.length === 1) {
            newDomain = conditions;
        } else {
            newDomain = [];
            // Prepend OR operators (N-1)
            for (let i = 0; i < conditions.length - 1; i++) {
                newDomain.push('|');
            }
            newDomain.push(...conditions);
        }

        try {
            searchModel.createNewFilters([{
                description: newDescription,
                domain: newDomain,
                type: 'filter',
            }]);
        } catch (e) {
            console.error('[HLV Filter] Failed:', e);
        }
    },

    /**
     * Apply select filter
     */
    async _hlvApplySelectFilter(fieldName, label, value, displayLabel) {
        console.log('[HLV Filter] Select:', fieldName, value);

        const controller = _hlvCurrentController;
        if (!controller) return;

        const searchModel = controller.env.searchModel;
        if (!searchModel?.createNewFilters) return;

        // 1. Identify active filters for this field
        const query = searchModel.query || [];
        const searchItems = searchModel.searchItems || {};
        const activeLabels = new Set();
        const activeValues = new Set();
        const filterIdsToRemove = [];

        // Check active filters to find existing selections
        for (const queryItem of query) {
            const itemId = queryItem.searchItemId;
            const item = searchItems[itemId];

            if (item && item.description && item.description.startsWith(`${label}: `)) {
                filterIdsToRemove.push(itemId);

                // Parse existing labels from description (e.g. "Status: Draft or Sent")
                // Note: We only have labels here, not values.
                // We rely on the fact that we are rebuilding the filter from scratch based on toggled logic.
                // HOWEVER, retrieving the *value* (ID) from the label is hard without a map.
                // Simplified approach: 
                // We will rely on `searchModel.query` to find the exact domain to extract values?
                // Parsing domain is more reliable than description.

                const domain = item.domain;
                if (domain) {
                    // Domain could be [['field', '=', 'val']] or ['|', ['field','=','v1'], ['field','=','v2']]
                    // or nested: ['|', '|', cond1, cond2, cond3]
                    this._hlvExtractValuesFromDomain(domain, fieldName, activeValues);
                }
            }
        }

        // 2. Remove existing filters
        for (const id of filterIdsToRemove) {
            try {
                if (searchModel.toggleSearchItem) {
                    searchModel.toggleSearchItem(id);
                } else {
                    searchModel.deactivateGroup(id);
                }
            } catch (e) {
                console.error('[HLV Filter] Remove failed:', e);
            }
        }

        if (filterIdsToRemove.length > 0) {
            await new Promise(resolve => setTimeout(resolve, 50));
        }

        if (value === '') {
            // "All" selected -> do nothing (already cleared)
            return;
        }

        // 3. Toggle the new value
        if (activeValues.has(value)) {
            activeValues.delete(value);
        } else {
            activeValues.add(value);
        }

        if (activeValues.size === 0) return;

        // 4. Build new Domain and Description
        const valueArray = Array.from(activeValues);
        let newDomain;
        let newDescription;

        // Helper to find label for a value
        const getLabelForValue = (val) => {
            // Try to match with the current selection if possible, or we need the options list.
            // Since we don't have the options list here easily without passing it, 
            // checking if 'value' matches 'val' is the best we can do for the *current* click.
            // For others, we might resort to just showing the value if we can't map it.
            // IMPROVEMENT: Pass options or store map.
            // For now, if we match the clicked one, use displayLabel. 
            // If not, we might be stuck with the value or need to lookup.
            // Let's rely on `SELECTION_FIELDS` global which is available in this file.
            const resModel = controller.props.resModel;
            const options = getSelectionOptions(fieldName, resModel);
            const opt = options?.find(o => o.value === val);
            return opt ? opt.label : val;
        };

        const labelArray = valueArray.map(getLabelForValue);

        if (valueArray.length === 1) {
            newDomain = [[fieldName, '=', valueArray[0]]];
            newDescription = `${label}: ${labelArray[0]} `;
        } else {
            newDomain = [];
            // Add OR operators
            // N items need N-1 ORs
            for (let i = 0; i < valueArray.length - 1; i++) {
                newDomain.push('|');
            }
            valueArray.forEach(val => {
                newDomain.push([fieldName, '=', val]);
            });
            newDescription = `${label}: ${labelArray.join(' hoặc ')} `;
        }

        try {
            searchModel.createNewFilters([{
                description: newDescription,
                domain: newDomain,
                type: 'filter',
            }]);
        } catch (e) {
            console.error('[HLV Filter] Failed:', e);
        }
    },

    /**
     * Helper to extract values from a domain tree recursively
     */
    _hlvExtractValuesFromDomain(domain, fieldName, valueSet) {
        if (!Array.isArray(domain)) return;

        // Support matching against multiple fields (e.g. mapped fields)
        const fields = Array.isArray(fieldName) ? fieldName : [fieldName];

        // Single condition: ['field', '=', 'val']
        if (domain.length === 3 && fields.includes(domain[0]) && (domain[1] === '=' || domain[1] === 'ilike')) {
            valueSet.add(domain[2]);
            return;
        }

        // Recursive OR/AND/list
        for (const element of domain) {
            if (Array.isArray(element)) {
                this._hlvExtractValuesFromDomain(element, fieldName, valueSet);
            }
        }
    },

    /**
     * Apply date range filter
     */

    async _hlvApplyDateFilter(fieldName, label, fromValue, toValue) {
        console.log('[HLV Filter] Date:', fieldName, fromValue, toValue);

        const controller = _hlvCurrentController;
        if (!controller) return;

        const searchModel = controller.env.searchModel;
        if (!searchModel?.createNewFilters) return;

        await this._hlvRemoveExistingFilters(label);

        let domain = [];
        let description = `${label}: `;

        if (fromValue && toValue) {
            const utcStart = toUTCDateTime(fromValue, '00:00:00');
            const utcEnd = toUTCDateTime(toValue, '23:59:59');
            domain = [
                [fieldName, '>=', utcStart],
                [fieldName, '<=', utcEnd]
            ];
            description += `${new Date(fromValue).toLocaleDateString('vi-VN')} - ${new Date(toValue).toLocaleDateString('vi-VN')} `;
        } else if (fromValue) {
            const utcStart = toUTCDateTime(fromValue, '00:00:00');
            domain = [[fieldName, '>=', utcStart]];
            description += `từ ${new Date(fromValue).toLocaleDateString('vi-VN')} `;
        } else if (toValue) {
            const utcEnd = toUTCDateTime(toValue, '23:59:59');
            domain = [[fieldName, '<=', utcEnd]];
            description += `đến ${new Date(toValue).toLocaleDateString('vi-VN')} `;
        }

        if (domain.length === 0) return;

        try {
            searchModel.createNewFilters([{
                description: description,
                domain: domain,
                type: 'filter',
            }]);
        } catch (e) {
            console.error('[HLV Filter] Failed:', e);
        }
    },

    /**
     * Remove existing filters for a field label
     */
    async _hlvRemoveExistingFilters(label) {
        const controller = _hlvCurrentController;
        if (!controller) return;

        const searchModel = controller.env.searchModel;
        if (!searchModel) return;

        const query = searchModel.query || [];
        const searchItems = searchModel.searchItems || {};
        const filterIdsToRemove = [];

        for (const queryItem of query) {
            const itemId = queryItem.searchItemId;
            const item = searchItems[itemId];

            if (item?.description?.startsWith(`${label}: `)) {
                filterIdsToRemove.push(itemId);
            }
        }

        for (const id of filterIdsToRemove) {
            try {
                if (searchModel.toggleSearchItem) {
                    searchModel.toggleSearchItem(id);
                } else {
                    searchModel.deactivateGroup(id);
                }
            } catch (e) {
                console.error('[HLV Filter] Remove failed:', e);
            }
        }

        if (filterIdsToRemove.length > 0) {
            await new Promise(resolve => setTimeout(resolve, 50));
        }
    },

    /**
     * Clear filter for a field
     */
    async _hlvClearFilter(fieldName, label) {
        await this._hlvRemoveExistingFilters(label);
        console.log('[HLV Filter] Cleared:', label);
    },

    /**
     * Show Warehouse Filter Dropdown (ported from PO preview)
     */
    async _hlvShowWarehouseFilterDropdown(triggerBtn, label) {
        document.querySelectorAll('.hlv-filter-dropdown-portal').forEach(d => d.remove());

        const rect = triggerBtn.getBoundingClientRect();

        const dropdown = document.createElement('div');
        dropdown.className = 'hlv-filter-dropdown-portal';
        dropdown.style.cssText = `
            position: fixed;
            top: ${rect.bottom + 4}px;
            left: ${Math.max(10, rect.left - 80)}px;
            min-width: 180px;
            background: #fff;
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
            z-index: 10000;
            overflow: hidden;
        `;

        dropdown.innerHTML = '<div style="padding: 10px 16px; text-align: center; color: #666;">Đang tải...</div>';
        document.body.appendChild(dropdown);

        // Fetch warehouses (picking types)
        const controller = _hlvCurrentController;
        if (!controller) {
            dropdown.innerHTML = '<div style="padding: 10px 16px; text-align: center; color: #d9534f;">Lỗi tải dữ liệu</div>';
            return;
        }

        const orm = controller.env.services.orm;
        let warehouses = [];

        try {
            warehouses = await orm.searchRead(
                'stock.picking.type',
                [['code', '=', 'incoming']],
                ['id', 'name', 'warehouse_id'],
                { order: 'name' }
            );
        } catch (e) {
            console.error('[HLV] Failed to fetch picking types:', e);
            dropdown.innerHTML = '<div style="padding: 10px 16px; text-align: center; color: #d9534f;">Lỗi tải dữ liệu</div>';
            return;
        }

        dropdown.innerHTML = '';

        const items = [
            ...warehouses.map(pt => ({
                value: pt.id,
                label: pt.warehouse_id ? pt.warehouse_id[1] : pt.name
            })),
            { value: '', label: '— Tất cả —', color: '#714B67' }
        ];

        if (items.length === 1) {
            dropdown.innerHTML = '<div style="padding: 10px 16px; text-align: center; color: #666;">Không có dữ liệu</div>';
            return;
        }

        items.forEach((item, idx) => {
            const div = document.createElement('div');
            div.className = 'hlv-filter-dropdown-item';
            div.innerHTML = item.label;
            div.style.cssText = `
                padding: 10px 16px;
                cursor: pointer;
                font-size: 0.9rem;
                color: ${item.value === '' ? '#714B67' : '#333'};
                font-weight: ${item.value === '' ? '600' : '400'};
                border-bottom: ${idx < items.length - 1 ? '1px solid #f0f0f0' : 'none'};
                transition: background-color 0.15s;
            `;

            div.addEventListener('mouseenter', () => div.style.backgroundColor = '#f8f4f7');
            div.addEventListener('mouseleave', () => div.style.backgroundColor = '');
            div.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropdown.remove();
                this._hlvApplyWarehouseFilter(item.value, item.label, label);
            });

            dropdown.appendChild(div);
        });

        this._hlvSetupPopupClose(dropdown, triggerBtn);
    },

    /**
     * Apply Warehouse Filter (Filter by picking_type_id)
     */
    async _hlvApplyWarehouseFilter(value, valueLabel, label) {
        console.log('[HLV] Warehouse filter:', value, valueLabel);

        const controller = _hlvCurrentController;
        if (!controller) return;

        const searchModel = controller.env.searchModel;
        if (!searchModel?.createNewFilters) return;

        // Remove existing warehouse filters (matching label "Kho nhận" or similar passed)
        // Usually label is "Kho nhận" from column header
        const query = searchModel.query || [];
        const searchItems = searchModel.searchItems || {};
        const activeIds = new Set();
        const filterIdsToRemove = [];

        for (const queryItem of query) {
            const itemId = queryItem.searchItemId;
            const item = searchItems[itemId];
            if (item && item.description && item.description.startsWith(`${label}: `)) {
                filterIdsToRemove.push(itemId);
                // Extract IDs from domain if we want toggle logic?
                // The original code uses Map<name, id>. 
                // Let's simplify and use the same toggle logic as other filters if we want multi-select.
                // Or single select? The original PO panel seemed to support multi.

                const domain = item.domain;
                if (domain) {
                    this._hlvExtractValuesFromDomain(domain, 'picking_type_id', activeIds);
                }
            }
        }

        for (const id of filterIdsToRemove) {
            try {
                if (searchModel.toggleSearchItem) {
                    searchModel.toggleSearchItem(id);
                } else {
                    searchModel.deactivateGroup(id);
                }
            } catch (e) {
                console.error('[HLV] Remove failed:', e);
            }
        }

        if (filterIdsToRemove.length > 0) {
            await new Promise(resolve => setTimeout(resolve, 50));
        }

        if (value === '') return; // Clear

        // Toggle
        if (activeIds.has(value)) {
            activeIds.delete(value);
        } else {
            activeIds.add(value);
        }

        if (activeIds.size === 0) return;

        // Build Domain
        // Domain is picking_type_id = value
        const idArray = Array.from(activeIds);
        let newDomain;
        let newDescription;

        // We need labels for description. Since we only passed one label, 
        // if we have multiple IDs we might need to fetch names or just show counts/IDs?
        // Limitation: If we toggle multiple, we lose the labels of previous ones unless we store map.
        // For now, let's just use the current label if single, or generic "Multiple" if multiple?
        // Or re-implement map logic? 
        // Simplest: Just use valueLabel for single. For multiple, maybe join IDs (not pretty)?
        // Original code used map to store names. 
        // Let's stick to single select or simple additive description? 
        // Actually, let's just use the label passed. If multiple, it will append? No, we rebuild filter.
        // Let's assume user clicks one by one.
        // Better: Use `valueLabel` for the current one. 
        // Recovering labels for existing IDs is hard without map.
        // **Compromise**: Just construct description with current label if single. 
        // If multiple, maybe we shouldn't support multi for warehouse yet to be safe, 
        // OR we try to keep it simple.

        if (idArray.length === 1) {
            newDomain = [['picking_type_id', '=', idArray[0]]];
            // Ideally we want the warehouse name here.
            newDescription = `${label}: ${valueLabel} `;
        } else {
            newDomain = [];
            for (let i = 0; i < idArray.length - 1; i++) newDomain.push('|');
            idArray.forEach(id => newDomain.push(['picking_type_id', '=', id]));
            // We can't easily reconstruct the names without fetching.
            // Just show "Multiple" or similar?
            // Or... just use the last label?
            // Let's assume single select is dominant use case or user accepts less perfect label.
            newDescription = `${label}: ${idArray.length} Kho`;
        }

        try {
            searchModel.createNewFilters([{
                description: newDescription,
                domain: newDomain,
                type: 'filter',
            }]);
        } catch (e) {
            console.error('[HLV] Failed:', e);
        }
    },
});
