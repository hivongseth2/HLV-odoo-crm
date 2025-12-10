/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";
import { ListController } from "@web/views/list/list_controller";
import { onMounted, onPatched } from "@odoo/owl";

// Store reference to current controller for use in ListRenderer
let _hlvCurrentController = null;

/**
 * Column filter configuration for stock.picking
 */
const FILTER_CONFIG = {
    'name': { type: 'text', label: 'Tham chiếu', field: 'name' },
    'x_studio_lin_h_1': { type: 'text', label: 'Liên hệ', field: 'x_studio_lin_h_1' },
    'location_id': { type: 'text', label: 'Từ', field: 'location_id.complete_name' },
    'location_dest_id': { type: 'text', label: 'Đến', field: 'location_dest_id.complete_name' },
    'date': { type: 'date', label: 'Ngày tạo', field: 'date' },
    'scheduled_date': { type: 'date', label: 'Ngày lên lịch', field: 'scheduled_date' },
    'date_deadline': { type: 'date', label: 'Ngày hạn', field: 'date_deadline' },
    'origin': { type: 'text', label: 'Chứng từ gốc', field: 'origin' },
    'batch_id': { type: 'text', label: 'Lệnh chuyển lô', field: 'batch_id.name' },
    'state': {
        type: 'select',
        label: 'Trạng thái',
        field: 'state',
        options: [
            { value: 'draft', label: 'Nháp' },
            { value: 'waiting', label: 'Đang chờ' },
            { value: 'confirmed', label: 'Chờ xử lý' },
            { value: 'assigned', label: 'Sẵn sàng' },
            { value: 'done', label: 'Hoàn thành' },
            { value: 'cancel', label: 'Đã hủy' },
        ]
    },
};

/**
 * Patch ListController for stock.picking
 */
patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);

        if (this.props.resModel === 'stock.picking') {
            _hlvCurrentController = this;
        }
    },
});

/**
 * Patch ListRenderer to add column filters for stock.picking
 */
patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);

        if (this.props.list?.resModel === 'stock.picking') {
            onMounted(() => {
                this._hlvAddColumnFilters();
            });
            onPatched(() => {
                this._hlvAddColumnFilters();
            });
        }
    },

    /**
     * Add filter buttons to all configured column headers
     */
    _hlvAddColumnFilters() {
        if (this.props.list?.resModel !== 'stock.picking') return;

        const tableEl = this.tableRef?.el;
        if (!tableEl) return;

        // Add filter to each configured column
        Object.keys(FILTER_CONFIG).forEach(fieldName => {
            const header = tableEl.querySelector(`th[data-name="${fieldName}"]`);
            if (!header || header.dataset.hlvFilterAdded) return;
            header.dataset.hlvFilterAdded = 'true';

            const config = FILTER_CONFIG[fieldName];
            const filterBtn = document.createElement('button');
            filterBtn.className = 'btn btn-link p-0 hlv-filter-btn ms-1';
            filterBtn.type = 'button';
            filterBtn.title = `Lọc theo ${config.label}`;
            filterBtn.innerHTML = '<i class="fa fa-filter" style="font-size: 10px; opacity: 0.6;"></i>';

            filterBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this._hlvShowFilterPopup(filterBtn, fieldName, config);
            });

            header.appendChild(filterBtn);
        });
    },

    /**
     * Show filter popup based on field type
     */
    _hlvShowFilterPopup(triggerBtn, fieldName, config) {
        // Remove existing popups
        document.querySelectorAll('.hlv-filter-popup').forEach(p => p.remove());

        const rect = triggerBtn.getBoundingClientRect();

        const popup = document.createElement('div');
        popup.className = 'hlv-filter-popup';
        popup.style.cssText = `
            position: fixed;
            top: ${rect.bottom + 4}px;
            left: ${Math.max(10, rect.left - 100)}px;
            min-width: 200px;
            background: #fff;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
            z-index: 10000;
            padding: 12px;
        `;

        let inputHtml = '';

        if (config.type === 'text') {
            inputHtml = `
                <input type="text" class="form-control form-control-sm hlv-filter-input"
                       placeholder="Nhập ${config.label}..." autofocus>
                <div class="mt-2 text-muted small">Nhấn Enter để lọc</div>
            `;
        } else if (config.type === 'date') {
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
        } else if (config.type === 'select') {
            const optionsHtml = config.options.map(opt =>
                `<option value="${opt.value}">${opt.label}</option>`
            ).join('');
            inputHtml = `
                <select class="form-select form-select-sm hlv-filter-select">
                    <option value="">-- Chọn ${config.label} --</option>
                    ${optionsHtml}
                </select>
                <div class="mt-2 text-muted small">Chọn để lọc</div>
            `;
        }

        popup.innerHTML = `
            <div class="hlv-filter-header mb-2">
                <strong style="color: #714B67;">${config.label}</strong>
            </div>
            ${inputHtml}
        `;

        document.body.appendChild(popup);

        // Setup event handlers based on type
        if (config.type === 'text') {
            const input = popup.querySelector('.hlv-filter-input');
            input.focus();
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    const value = input.value.trim();
                    popup.remove();
                    if (value) {
                        this._hlvApplyTextFilter(fieldName, config, value);
                    }
                } else if (e.key === 'Escape') {
                    popup.remove();
                }
            });
        } else if (config.type === 'date') {
            const applyBtn = popup.querySelector('.hlv-filter-apply');
            applyBtn.addEventListener('click', () => {
                const dateFrom = popup.querySelector('.hlv-filter-date-from').value;
                const dateTo = popup.querySelector('.hlv-filter-date-to').value;
                popup.remove();
                if (dateFrom || dateTo) {
                    this._hlvApplyDateFilter(fieldName, config, dateFrom, dateTo);
                }
            });
        } else if (config.type === 'select') {
            const select = popup.querySelector('.hlv-filter-select');
            select.addEventListener('change', () => {
                const value = select.value;
                popup.remove();
                if (value) {
                    this._hlvApplySelectFilter(fieldName, config, value);
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
     * Apply text filter using Odoo searchModel
     */
    _hlvApplyTextFilter(fieldName, config, value) {
        console.log('[HLV Stock Filter] Text filter:', fieldName, value);

        const controller = _hlvCurrentController;
        if (!controller) {
            console.error('[HLV Stock Filter] Controller not available');
            return;
        }

        const searchModel = controller.env.searchModel;
        if (!searchModel || !searchModel.createNewFilters) {
            console.error('[HLV Stock Filter] SearchModel not available');
            return;
        }

        // Build domain based on field
        let domain;
        if (config.field.includes('.')) {
            // Relational field
            domain = [[config.field, 'ilike', value]];
        } else {
            domain = [[fieldName, 'ilike', value]];
        }

        try {
            searchModel.createNewFilters([{
                description: `${config.label}: ${value}`,
                domain: domain,
                type: 'filter',
            }]);
            console.log('[HLV Stock Filter] Applied text filter');
        } catch (e) {
            console.error('[HLV Stock Filter] Failed to create filter:', e);
        }
    },

    /**
     * Apply date range filter
     */
    _hlvApplyDateFilter(fieldName, config, dateFrom, dateTo) {
        console.log('[HLV Stock Filter] Date filter:', fieldName, dateFrom, dateTo);

        const controller = _hlvCurrentController;
        if (!controller) return;

        const searchModel = controller.env.searchModel;
        if (!searchModel || !searchModel.createNewFilters) return;

        // Build domain
        const domain = [];
        if (dateFrom) {
            domain.push([fieldName, '>=', dateFrom + ' 00:00:00']);
        }
        if (dateTo) {
            domain.push([fieldName, '<=', dateTo + ' 23:59:59']);
        }

        if (domain.length === 0) return;

        // Build description
        let description = config.label + ': ';
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
            console.log('[HLV Stock Filter] Applied date filter');
        } catch (e) {
            console.error('[HLV Stock Filter] Failed to create date filter:', e);
        }
    },

    /**
     * Apply select filter (for state)
     */
    _hlvApplySelectFilter(fieldName, config, value) {
        console.log('[HLV Stock Filter] Select filter:', fieldName, value);

        const controller = _hlvCurrentController;
        if (!controller) return;

        const searchModel = controller.env.searchModel;
        if (!searchModel || !searchModel.createNewFilters) return;

        // Find label for display
        const option = config.options.find(o => o.value === value);
        const label = option ? option.label : value;

        try {
            searchModel.createNewFilters([{
                description: `${config.label}: ${label}`,
                domain: [[fieldName, '=', value]],
                type: 'filter',
            }]);
            console.log('[HLV Stock Filter] Applied select filter');
        } catch (e) {
            console.error('[HLV Stock Filter] Failed to create select filter:', e);
        }
    },
});
