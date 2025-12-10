/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { ListController } from "@web/views/list/list_controller";
import { onMounted, onPatched } from "@odoo/owl";

// Store reference to current controller
let _hlvCurrentController = null;

// Models to apply filters
const ENABLED_MODELS = [
    // 'purchase.order',
    'stock.picking',
    'sale.order',
];

// Selection field options by model
const SELECTION_FIELDS = {
    'state': {
        'purchase.order': [
            { value: 'draft', label: 'RFQ', color: '#6c757d' },
            { value: 'sent', label: 'RFQ Sent', color: '#17a2b8' },
            { value: 'to approve', label: 'To Approve', color: '#ffc107' },
            { value: 'purchase', label: 'Purchase Order', color: '#28a745' },
            { value: 'done', label: 'Locked', color: '#714B67' },
            { value: 'cancel', label: 'Cancelled', color: '#dc3545' },
        ],
        'stock.picking': [
            { value: 'draft', label: 'Nháp', color: '#6c757d' },
            { value: 'waiting', label: 'Đang chờ', color: '#ffc107' },
            { value: 'confirmed', label: 'Chờ xử lý', color: '#17a2b8' },
            { value: 'assigned', label: 'Sẵn sàng', color: '#28a745' },
            { value: 'done', label: 'Hoàn thành', color: '#714B67' },
            { value: 'cancel', label: 'Đã hủy', color: '#dc3545' },
        ],
        'sale.order': [
            { value: 'draft', label: 'Báo giá', color: '#6c757d' },
            { value: 'sent', label: 'Đã gửi', color: '#17a2b8' },
            { value: 'sale', label: 'Đơn hàng', color: '#28a745' },
            { value: 'done', label: 'Khóa', color: '#714B67' },
            { value: 'cancel', label: 'Đã hủy', color: '#dc3545' },
        ],
    },
    'invoice_status': {
        'purchase.order': [
            { value: 'no', label: 'Chưa thanh toán', color: '#6c757d' },
            { value: 'to invoice', label: 'Cần thanh toán', color: '#ffc107' },
            { value: 'invoiced', label: 'Đã thanh toán', color: '#28a745' },
        ],
        'sale.order': [
            { value: 'upselling', label: 'Cơ hội Up-sell', color: '#17a2b8' },
            { value: 'invoiced', label: 'Đã thanh toán', color: '#28a745' },
            { value: 'to invoice', label: 'Cần thanh toán', color: '#ffc107' },
            { value: 'no', label: 'Không', color: '#6c757d' },
        ],
    },
    'receipt_status': {
        'purchase.order': [
            { value: 'pending', label: 'Chưa nhận', color: '#ffc107' },
            { value: 'partial', label: 'Đã nhận một phần', color: '#17a2b8' },
            { value: 'full', label: 'Đã nhận hết', color: '#28a745' },
        ],
    },
};

// Date field patterns
const DATE_FIELD_PATTERNS = [
    'date', 'datetime', 'scheduled', 'deadline', 'create_date', 'write_date',
    'date_order', 'date_planned', 'date_done', 'commitment_date', 'date_approve'
];

/**
 * Convert local date to UTC datetime string
 */
function toUTCDateTime(dateStr, timeStr) {
    if (!dateStr) return null;
    const localDate = new Date(`${dateStr}T${timeStr}`);
    return localDate.toISOString().replace('T', ' ').split('.')[0];
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
            onMounted(() => this._hlvAddUniversalFilters());
            onPatched(() => this._hlvAddUniversalFilters());
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

        const headers = tableEl.querySelectorAll('th[data-name]');

        headers.forEach(header => {
            const fieldName = header.dataset.name;
            if (!fieldName || fieldName === '__checkbox__') return;
            if (header.dataset.hlvFilterAdded) return;
            header.dataset.hlvFilterAdded = 'true';

            // Determine filter type
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

            const filterBtn = document.createElement('button');
            filterBtn.className = 'btn btn-link p-0 hlv-filter-btn ms-1';
            filterBtn.type = 'button';
            filterBtn.title = `Lọc theo ${label}`;
            filterBtn.innerHTML = '<i class="fa fa-filter"></i>';

            filterBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (filterType === 'select') {
                    this._hlvShowSelectDropdown(filterBtn, fieldName, label, options);
                } else if (filterType === 'date') {
                    this._hlvShowDateDropdown(filterBtn, fieldName, label);
                } else {
                    this._hlvShowTextPopup(filterBtn, fieldName, label);
                }
            });

            header.appendChild(filterBtn);
        });
    },

    /**
     * Show text search popup (same style as PO preview supplier search)
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
     * Show select dropdown (same style as PO preview receipt status)
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

        // Add "Tất cả" option at the end
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
     * Show date range picker (same style as PO preview)
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

        const searchModel = controller.env.searchModel;
        if (!searchModel?.createNewFilters) return;

        // Remove existing filters for this field
        await this._hlvRemoveExistingFilters(label);

        const domain = [[fieldName, 'ilike', value]];
        const description = `${label}: ${value}`;

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
     * Apply select filter
     */
    async _hlvApplySelectFilter(fieldName, label, value, displayLabel) {
        console.log('[HLV Filter] Select:', fieldName, value);

        const controller = _hlvCurrentController;
        if (!controller) return;

        const searchModel = controller.env.searchModel;
        if (!searchModel?.createNewFilters) return;

        // Remove existing filters for this field
        await this._hlvRemoveExistingFilters(label);

        if (!value) return; // "Tất cả" selected - just clear

        const domain = [[fieldName, '=', value]];
        const description = `${label}: ${displayLabel}`;

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
     * Apply date range filter
     */
    async _hlvApplyDateFilter(fieldName, label, fromValue, toValue) {
        console.log('[HLV Filter] Date:', fieldName, fromValue, toValue);

        const controller = _hlvCurrentController;
        if (!controller) return;

        const searchModel = controller.env.searchModel;
        if (!searchModel?.createNewFilters) return;

        // Remove existing filters for this field
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
            description += `${new Date(fromValue).toLocaleDateString('vi-VN')} - ${new Date(toValue).toLocaleDateString('vi-VN')}`;
        } else if (fromValue) {
            const utcStart = toUTCDateTime(fromValue, '00:00:00');
            domain = [[fieldName, '>=', utcStart]];
            description += `từ ${new Date(fromValue).toLocaleDateString('vi-VN')}`;
        } else if (toValue) {
            const utcEnd = toUTCDateTime(toValue, '23:59:59');
            domain = [[fieldName, '<=', utcEnd]];
            description += `đến ${new Date(toValue).toLocaleDateString('vi-VN')}`;
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

            if (item?.description?.startsWith(`${label}:`)) {
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
});
