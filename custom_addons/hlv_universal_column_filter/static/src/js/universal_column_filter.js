/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { ListController } from "@web/views/list/list_controller";
import { onMounted, onPatched } from "@odoo/owl";

// Store reference to current controller
let _hlvCurrentController = null;

// Models to apply filters (không bao gồm purchase.order vì đã có module riêng)
const ENABLED_MODELS = [
    'stock.picking',
    'sale.order',
];

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
};

// Selection field options by model
const SELECTION_FIELDS = {
    'state': {
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
        'sale.order': [
            { value: 'upselling', label: 'Cơ hội Up-sell', color: '#17a2b8' },
            { value: 'invoiced', label: 'Đã thanh toán', color: '#28a745' },
            { value: 'to invoice', label: 'Cần thanh toán', color: '#ffc107' },
            { value: 'no', label: 'Không', color: '#6c757d' },
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

        const searchModel = controller.env.searchModel;
        if (!searchModel?.createNewFilters) return;

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

        await this._hlvRemoveExistingFilters(label);

        if (!value) return;

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
