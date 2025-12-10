/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { ListController } from "@web/views/list/list_controller";
import { onMounted, onPatched } from "@odoo/owl";

// Store reference to current controller
let _hlvCurrentController = null;

// Models to apply filters (can be extended)
const ENABLED_MODELS = [
    'purchase.order',
    'stock.picking',
    'sale.order',
];

// Known selection fields with options
const SELECTION_FIELDS = {
    'state': {
        'purchase.order': [
            { value: 'draft', label: 'RFQ' },
            { value: 'sent', label: 'RFQ Sent' },
            { value: 'to approve', label: 'To Approve' },
            { value: 'purchase', label: 'Purchase Order' },
            { value: 'done', label: 'Locked' },
            { value: 'cancel', label: 'Cancelled' },
        ],
        'stock.picking': [
            { value: 'draft', label: 'Nháp' },
            { value: 'waiting', label: 'Đang chờ' },
            { value: 'confirmed', label: 'Chờ xử lý' },
            { value: 'assigned', label: 'Sẵn sàng' },
            { value: 'done', label: 'Hoàn thành' },
            { value: 'cancel', label: 'Đã hủy' },
        ],
        'sale.order': [
            { value: 'draft', label: 'Quotation' },
            { value: 'sent', label: 'Quotation Sent' },
            { value: 'sale', label: 'Sales Order' },
            { value: 'done', label: 'Locked' },
            { value: 'cancel', label: 'Cancelled' },
        ],
    },
    'invoice_status': {
        'purchase.order': [
            { value: 'no', label: 'Chưa thanh toán' },
            { value: 'to invoice', label: 'Cần thanh toán' },
            { value: 'invoiced', label: 'Đã thanh toán' },
        ],
        'sale.order': [
            { value: 'no', label: 'Chưa thanh toán' },
            { value: 'to invoice', label: 'Cần thanh toán' },
            { value: 'invoiced', label: 'Đã thanh toán' },
        ],
    },
};

// Date field patterns
const DATE_FIELD_PATTERNS = [
    'date', 'datetime', 'scheduled', 'deadline', 'create_date', 'write_date',
    'date_order', 'date_planned', 'date_done', 'commitment_date'
];

/**
 * Detect if a field is a date type based on column header content or field name
 */
function isDateField(fieldName, headerEl) {
    // Check by field name pattern
    const lowerName = fieldName.toLowerCase();
    if (DATE_FIELD_PATTERNS.some(p => lowerName.includes(p))) {
        return true;
    }

    // Check by column class
    if (headerEl) {
        const classList = headerEl.className || '';
        if (classList.includes('o_date') || classList.includes('datetime')) {
            return true;
        }
    }

    return false;
}

/**
 * Detect if a field is a selection type
 */
function isSelectionField(fieldName, resModel) {
    return SELECTION_FIELDS[fieldName] && SELECTION_FIELDS[fieldName][resModel];
}

/**
 * Get selection options for a field
 */
function getSelectionOptions(fieldName, resModel) {
    if (SELECTION_FIELDS[fieldName] && SELECTION_FIELDS[fieldName][resModel]) {
        return SELECTION_FIELDS[fieldName][resModel];
    }
    return null;
}

/**
 * Get field label from header element
 */
function getFieldLabel(headerEl) {
    // Try to get text content, excluding child elements like sort icons
    const clone = headerEl.cloneNode(true);
    // Remove buttons and icons
    clone.querySelectorAll('button, .fa, .o_resize').forEach(el => el.remove());
    return clone.textContent.trim() || 'Field';
}

/**
 * Patch ListController to store reference
 */
patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);

        if (ENABLED_MODELS.includes(this.props.resModel)) {
            _hlvCurrentController = this;
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
            });
            onPatched(() => {
                this._hlvAddUniversalFilters();
            });
        }
    },

    /**
     * Add filter buttons to ALL column headers dynamically
     */
    _hlvAddUniversalFilters() {
        const resModel = this.props.list?.resModel;
        if (!resModel || !ENABLED_MODELS.includes(resModel)) return;

        const tableEl = this.tableRef?.el;
        if (!tableEl) return;

        // Get all column headers with data-name attribute
        const headers = tableEl.querySelectorAll('th[data-name]');

        headers.forEach(header => {
            const fieldName = header.dataset.name;
            if (!fieldName) return;

            // Skip if already added
            if (header.dataset.hlvFilterAdded) return;
            header.dataset.hlvFilterAdded = 'true';

            // Skip checkbox column
            if (fieldName === '__checkbox__') return;

            // Determine filter type
            let filterType = 'text';
            let options = null;

            if (isSelectionField(fieldName, resModel)) {
                filterType = 'select';
                options = getSelectionOptions(fieldName, resModel);
            } else if (isDateField(fieldName, header)) {
                filterType = 'date';
            }

            const label = getFieldLabel(header);

            // Create filter button
            const filterBtn = document.createElement('button');
            filterBtn.className = 'btn btn-link p-0 hlv-filter-btn';
            filterBtn.type = 'button';
            filterBtn.title = `Lọc theo ${label}`;
            filterBtn.innerHTML = '<i class="fa fa-filter"></i>';

            filterBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this._hlvShowFilterPopup(filterBtn, fieldName, label, filterType, options);
            });

            header.appendChild(filterBtn);
        });
    },

    /**
     * Show filter popup
     */
    _hlvShowFilterPopup(triggerBtn, fieldName, label, filterType, options) {
        // Remove existing popups
        document.querySelectorAll('.hlv-filter-popup').forEach(p => p.remove());

        const rect = triggerBtn.getBoundingClientRect();

        const popup = document.createElement('div');
        popup.className = 'hlv-filter-popup';
        popup.style.cssText = `
            position: fixed;
            top: ${rect.bottom + 4}px;
            left: ${Math.max(10, rect.left - 100)}px;
            min-width: 220px;
            background: #fff;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
            z-index: 10000;
            padding: 12px;
        `;

        let inputHtml = '';

        if (filterType === 'text') {
            inputHtml = `
                <input type="text" class="form-control form-control-sm hlv-filter-input"
                       placeholder="Nhập ${label}..." autofocus>
                <div class="mt-2 text-muted small">Nhấn Enter để lọc</div>
            `;
        } else if (filterType === 'date') {
            inputHtml = `
                <div class="mb-2">
                    <label class="small text-muted">Từ ngày:</label>
                    <input type="date" class="form-control form-control-sm hlv-filter-date-from">
                </div>
                <div class="mb-2">
                    <label class="small text-muted">Đến ngày:</label>
                    <input type="date" class="form-control form-control-sm hlv-filter-date-to">
                </div>
                <button class="btn btn-sm btn-primary w-100 hlv-filter-apply">Áp dụng</button>
            `;
        } else if (filterType === 'select' && options) {
            const optionsHtml = options.map(opt =>
                `<option value="${opt.value}">${opt.label}</option>`
            ).join('');
            inputHtml = `
                <select class="form-select form-select-sm hlv-filter-select">
                    <option value="">-- Chọn ${label} --</option>
                    ${optionsHtml}
                </select>
                <div class="mt-2 text-muted small">Chọn để lọc</div>
            `;
        }

        popup.innerHTML = `
            <div class="hlv-filter-header mb-2">
                <strong style="color: #714B67;">${label}</strong>
            </div>
            ${inputHtml}
        `;

        document.body.appendChild(popup);

        // Setup event handlers
        if (filterType === 'text') {
            const input = popup.querySelector('.hlv-filter-input');
            input.focus();
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    const value = input.value.trim();
                    popup.remove();
                    if (value) {
                        this._hlvApplyFilter(fieldName, label, 'ilike', value);
                    }
                } else if (e.key === 'Escape') {
                    popup.remove();
                }
            });
        } else if (filterType === 'date') {
            const applyBtn = popup.querySelector('.hlv-filter-apply');
            applyBtn.addEventListener('click', () => {
                const dateFrom = popup.querySelector('.hlv-filter-date-from').value;
                const dateTo = popup.querySelector('.hlv-filter-date-to').value;
                popup.remove();
                if (dateFrom || dateTo) {
                    this._hlvApplyDateFilter(fieldName, label, dateFrom, dateTo);
                }
            });
        } else if (filterType === 'select') {
            const select = popup.querySelector('.hlv-filter-select');
            select.addEventListener('change', () => {
                const value = select.value;
                const selectedOption = options.find(o => o.value === value);
                popup.remove();
                if (value) {
                    this._hlvApplyFilter(fieldName, label, '=', value, selectedOption?.label);
                }
            });
        }

        // Close on click outside
        setTimeout(() => {
            document.addEventListener('click', function closePopup(e) {
                if (!popup.contains(e.target) && e.target !== triggerBtn) {
                    popup.remove();
                    document.removeEventListener('click', closePopup);
                }
            });
        }, 10);

        // Close on Escape
        document.addEventListener('keydown', function handleEsc(e) {
            if (e.key === 'Escape') {
                popup.remove();
                document.removeEventListener('keydown', handleEsc);
            }
        });
    },

    /**
     * Apply filter using Odoo searchModel
     */
    _hlvApplyFilter(fieldName, label, operator, value, displayValue = null) {
        console.log('[HLV Filter]', fieldName, operator, value);

        const controller = _hlvCurrentController;
        if (!controller) {
            console.error('[HLV Filter] Controller not available');
            return;
        }

        const searchModel = controller.env.searchModel;
        if (!searchModel || !searchModel.createNewFilters) {
            console.error('[HLV Filter] SearchModel not available');
            return;
        }

        const domain = [[fieldName, operator, value]];
        const description = `${label}: ${displayValue || value}`;

        try {
            searchModel.createNewFilters([{
                description: description,
                domain: domain,
                type: 'filter',
            }]);
            console.log('[HLV Filter] Applied filter');
        } catch (e) {
            console.error('[HLV Filter] Failed:', e);
        }
    },

    /**
     * Apply date range filter
     */
    _hlvApplyDateFilter(fieldName, label, dateFrom, dateTo) {
        console.log('[HLV Filter] Date:', fieldName, dateFrom, dateTo);

        const controller = _hlvCurrentController;
        if (!controller) return;

        const searchModel = controller.env.searchModel;
        if (!searchModel || !searchModel.createNewFilters) return;

        const domain = [];
        if (dateFrom) {
            domain.push([fieldName, '>=', dateFrom + ' 00:00:00']);
        }
        if (dateTo) {
            domain.push([fieldName, '<=', dateTo + ' 23:59:59']);
        }

        if (domain.length === 0) return;

        let description = label + ': ';
        if (dateFrom && dateTo) {
            description += `${dateFrom} → ${dateTo}`;
        } else if (dateFrom) {
            description += `từ ${dateFrom}`;
        } else {
            description += `đến ${dateTo}`;
        }

        try {
            searchModel.createNewFilters([{
                description: description,
                domain: domain,
                type: 'filter',
            }]);
            console.log('[HLV Filter] Applied date filter');
        } catch (e) {
            console.error('[HLV Filter] Failed:', e);
        }
    },
});
