/* Tab "Điểm đổi thưởng" trên trang /misa_sale_status: sale xác nhận điểm đổi thưởng đang chờ của
 * phiếu mình (server tra lại MISA, chỉ xác nhận phiếu đã thu đủ tiền); Hủy / Sửa / Tính lại chỉ
 * hiện khi bật trong Cài đặt Loyalty (server cũng chặn lại, ẩn nút chỉ là cho gọn).
 * Không tự có rpc/định dạng/toast — dùng chung bản của trang qua window.MsuSaleStatus. */
(function () {
    'use strict';

    var PAGE_SIZE = 50;
    var COLS = 7;
    var msu = window.MsuSaleStatus;
    var state = {
        search: '', page: 1, total: 0, totalPoints: 0, rows: [], selected: {}, loadedFor: null,
        allowCancel: false, allowEdit: false, action: null,
    };

    function el(id) { return document.getElementById(id); }

    function fmtPoints(n) { return (n || 0).toLocaleString('vi-VN'); }

    function paidBadgeClass(paidState) {
        if (paidState === 'paid') { return 'msl-badge-ok'; }
        if (paidState === 'unpaid' || paidState === 'partial') { return 'msl-badge-warn'; }
        return 'msl-badge-muted';
    }

    function selectedIds() {
        return Object.keys(state.selected).map(Number);
    }

    function renderRow(row) {
        var checked = state.selected[row.id] ? ' checked' : '';
        var sub = msu.isAdmin() && row.saler_code ? ' · ' + msu.esc(row.saler_code) : '';
        var editBtns = state.allowEdit
            ? '<button type="button" class="msu-btn msu-btn-outline-muted msu-btn-xs msl-edit-btn" data-id="' + row.id + '" title="Sửa số điểm"><i class="fa fa-pencil"></i></button>' +
              '<button type="button" class="msu-btn msu-btn-outline-muted msu-btn-xs msl-recalc-btn" data-id="' + row.id + '" title="Tính lại theo đơn bán hiện tại"><i class="fa fa-calculator"></i></button>'
            : '';
        return '<tr data-id="' + row.id + '">' +
            '<td class="msl-col-check"><input type="checkbox" class="msl-check" data-id="' + row.id + '"' + checked + '/></td>' +
            '<td class="msl-nowrap">' + msu.fmtDate(row.date) + '</td>' +
            '<td><b>' + msu.esc(row.partner) + '</b><div class="msu-muted msl-sub">' + msu.esc(row.account) + '</div></td>' +
            '<td>' + msu.esc(row.order) + '<div class="msu-muted msl-sub">' + msu.esc(row.picking) + sub + '</div></td>' +
            '<td class="msu-col-num"><b>' + fmtPoints(row.points) + '</b></td>' +
            '<td>' + (row.invoice_no ? 'HĐ ' + msu.esc(row.invoice_no) : '<span class="msu-muted">—</span>') +
                '<div><span class="msl-badge ' + paidBadgeClass(row.paid_state) + '">' + msu.esc(row.paid_label) + '</span></div></td>' +
            '<td class="msl-actions">' +
                '<button type="button" class="msu-btn msu-btn-outline-primary msu-btn-xs msl-check-btn" data-id="' + row.id + '" title="Tra lại MISA xem đã thu tiền chưa"><i class="fa fa-search"></i></button>' +
                editBtns +
                '<button type="button" class="msu-btn msu-btn-primary msu-btn-xs msl-confirm-one-btn" data-id="' + row.id + '" title="Xác nhận điểm này (tra MISA trước)"><i class="fa fa-check"></i></button>' +
            '</td></tr>';
    }

    function renderSelection() {
        var ids = selectedIds();
        var points = state.rows.reduce(function (sum, r) { return sum + (state.selected[r.id] ? r.points : 0); }, 0);
        el('msl-selected-info').textContent = ids.length ? 'Đã chọn ' + ids.length + ' dòng · ' + fmtPoints(points) + ' điểm' : '';
        el('msl-confirm-btn').disabled = !ids.length;
        el('msl-cancel-btn').disabled = !ids.length;
        el('msl-cancel-btn').style.display = state.allowCancel ? '' : 'none';
        el('msl-check-all').checked = state.rows.length > 0 && state.rows.every(function (r) { return state.selected[r.id]; });
    }

    function renderRows() {
        el('msl-tbody').innerHTML = state.rows.map(renderRow).join('');
        el('msl-empty').style.display = state.rows.length ? 'none' : '';
        el('msl-summary').innerHTML = state.total
            ? '<b>' + state.total + '</b> dòng chờ xác nhận · <b>' + fmtPoints(state.totalPoints) + '</b> điểm'
            : '';
        var pages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
        el('msl-pagination').style.display = pages > 1 ? '' : 'none';
        el('msl-page-label').textContent = 'Trang ' + state.page + '/' + pages + ' · ' + state.total + ' dòng';
        el('msl-prev').disabled = state.page <= 1;
        el('msl-next').disabled = state.page >= pages;
        renderSelection();
    }

    function load(pageNo) {
        var salerCode = msu.getSalerCode();
        if (!salerCode) { return; }
        state.page = pageNo || 1;
        state.loadedFor = salerCode;
        state.selected = {};
        el('msl-tbody').innerHTML = '<tr><td colspan="' + COLS + '" class="msu-muted"><i class="fa fa-spinner fa-spin"></i> Đang tải...</td></tr>';
        msu.rpc('/misa_sale_status/api/loyalty/list', {
            saler_code: salerCode, search: state.search,
            limit: PAGE_SIZE, offset: (state.page - 1) * PAGE_SIZE,
        }).then(function (res) {
            var data = res.data;
            state.rows = data.rows;
            state.total = data.total;
            state.totalPoints = data.total_points;
            state.allowCancel = data.allow_cancel;
            state.allowEdit = data.allow_edit;
            renderRows();
        }).catch(function (e) {
            el('msl-tbody').innerHTML = '';
            msu.toast('Lỗi tải điểm đổi thưởng: ' + e.message, 'error');
        });
    }

    function rowById(id) {
        return state.rows.find(function (r) { return r.id === Number(id); });
    }

    function confirmIds(ids, btn) {
        msu.setBtnLoading(btn, true);
        msu.rpc('/misa_sale_status/api/loyalty/confirm', {saler_code: msu.getSalerCode(), history_ids: ids}).then(function (res) {
            var r = res.data;
            if (r.confirmed) {
                msu.toast('Đã xác nhận ' + r.confirmed + ' dòng · ' + fmtPoints(r.confirmed_points) + ' điểm.', 'success');
            }
            r.skipped.forEach(function (s) {
                msu.toast('Chưa xác nhận ' + s.picking + ': ' + s.reason, 'error');
            });
            load(state.page);
        }).catch(function (e) {
            msu.toast(e.message, 'error');
        }).finally(function () { msu.setBtnLoading(btn, false); });
    }

    function checkPaid(btn) {
        var row = rowById(btn.dataset.id);
        msu.setBtnLoading(btn, true);
        msu.rpc('/misa_sale_status/api/loyalty/check_paid', {saler_code: msu.getSalerCode(), history_id: row.id}).then(function (res) {
            var r = res.data;
            msu.toast(row.picking + ': ' + r.label, r.paid_state === 'paid' ? 'success' : 'error');
            load(state.page);
        }).catch(function (e) {
            msu.setBtnLoading(btn, false);
            msu.toast(e.message, 'error');
        });
    }

    function recalculate(btn) {
        var row = rowById(btn.dataset.id);
        if (!window.confirm('Tính lại điểm đổi thưởng của ' + row.picking + ' theo đơn bán hiện tại?')) { return; }
        msu.setBtnLoading(btn, true);
        msu.rpc('/misa_sale_status/api/loyalty/recalculate', {saler_code: msu.getSalerCode(), history_id: row.id}).then(function (res) {
            msu.toast(row.picking + ': ' + fmtPoints(row.points) + ' → ' + fmtPoints(res.data.points) + ' điểm.', 'success');
            load(state.page);
        }).catch(function (e) {
            msu.setBtnLoading(btn, false);
            msu.toast(e.message, 'error');
        });
    }

    // Hủy (nhiều dòng) và Sửa (1 dòng) dùng chung 1 hộp thoại, chỉ khác ô số điểm.
    function openAction(mode, ids) {
        state.action = {mode: mode, ids: ids};
        var isEdit = mode === 'edit';
        var row = isEdit ? rowById(ids[0]) : null;
        el('msl-action-title').textContent = isEdit ? 'Sửa số điểm' : 'Hủy điểm chờ xác nhận';
        el('msl-action-target').textContent = isEdit
            ? row.partner + ' — ' + row.picking + ' — hiện ' + fmtPoints(row.points) + ' điểm'
            : ids.length + ' dòng đã chọn sẽ bị hủy, không vào số dư của khách.';
        el('msl-action-points-wrap').style.display = isEdit ? '' : 'none';
        el('msl-action-points').value = isEdit ? row.points : '';
        el('msl-action-reason').value = '';
        el('msl-action-error').textContent = '';
        el('msl-action-modal').style.display = '';
    }

    function saveAction(btn) {
        var action = state.action;
        var params = {saler_code: msu.getSalerCode(), reason: el('msl-action-reason').value.trim()};
        var url;
        if (action.mode === 'edit') {
            url = '/misa_sale_status/api/loyalty/edit';
            params.history_id = action.ids[0];
            params.point_amount = el('msl-action-points').value;
        } else {
            url = '/misa_sale_status/api/loyalty/cancel';
            params.history_ids = action.ids;
        }
        msu.setBtnLoading(btn, true);
        msu.rpc(url, params).then(function () {
            el('msl-action-modal').style.display = 'none';
            msu.toast(action.mode === 'edit' ? 'Đã sửa số điểm.' : 'Đã hủy ' + action.ids.length + ' dòng.', 'success');
            load(state.page);
        }).catch(function (e) {
            el('msl-action-error').textContent = e.message;
        }).finally(function () { msu.setBtnLoading(btn, false); });
    }

    function applySearch(value) {
        state.search = value.trim();
        el('msl-search').value = state.search;
        el('msl-search-clear').style.display = state.search ? '' : 'none';
        load(1);
    }

    function bindEvents() {
        document.addEventListener('msu:tab-shown', function (ev) {
            if (ev.detail.tab === 'loyalty' && state.loadedFor !== msu.getSalerCode()) { load(1); }
        });
        document.addEventListener('msu:saler-chosen', function () {
            if (msu.getActiveTab() === 'loyalty') { load(1); }
        });
        el('msl-search-btn').addEventListener('click', function () { applySearch(el('msl-search').value); });
        el('msl-search').addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter') { applySearch(this.value); }
        });
        el('msl-search-clear').addEventListener('click', function () { applySearch(''); });
        el('msl-refresh-btn').addEventListener('click', function () { load(state.page); });
        el('msl-prev').addEventListener('click', function () { load(state.page - 1); });
        el('msl-next').addEventListener('click', function () { load(state.page + 1); });
        el('msl-check-all').addEventListener('change', function () {
            var on = this.checked;
            state.selected = {};
            if (on) { state.rows.forEach(function (r) { state.selected[r.id] = true; }); }
            renderRows();
        });
        el('msl-tbody').addEventListener('change', function (ev) {
            if (!ev.target.classList.contains('msl-check')) { return; }
            if (ev.target.checked) {
                state.selected[ev.target.dataset.id] = true;
            } else {
                delete state.selected[ev.target.dataset.id];
            }
            renderSelection();
        });
        el('msl-tbody').addEventListener('click', function (ev) {
            var btn = ev.target.closest('.msl-check-btn, .msl-edit-btn, .msl-recalc-btn, .msl-confirm-one-btn');
            if (!btn) { return; }
            if (btn.classList.contains('msl-check-btn')) { checkPaid(btn); }
            if (btn.classList.contains('msl-edit-btn')) { openAction('edit', [Number(btn.dataset.id)]); }
            if (btn.classList.contains('msl-recalc-btn')) { recalculate(btn); }
            if (btn.classList.contains('msl-confirm-one-btn')) { confirmIds([Number(btn.dataset.id)], btn); }
        });
        el('msl-confirm-btn').addEventListener('click', function () { confirmIds(selectedIds(), this); });
        el('msl-cancel-btn').addEventListener('click', function () { openAction('cancel', selectedIds()); });
        el('msl-action-close').addEventListener('click', function () { el('msl-action-modal').style.display = 'none'; });
        el('msl-action-save').addEventListener('click', function () { saveAction(this); });
    }

    if (msu && el('msu-tab-loyalty')) { bindEvents(); }
})();
