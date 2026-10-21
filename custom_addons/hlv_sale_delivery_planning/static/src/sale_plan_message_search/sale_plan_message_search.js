/* Panel "Tìm tin nhắn" trên trang /sale_plan: sale tìm lại trao đổi cũ theo nội
 * dung, mã đơn / khách, người gửi, alias được nhắc (@Hân BC...) và thời gian.
 *
 * Toàn bộ UI nằm trong file này (CSS, nút navbar, panel, gọi API) — cùng kiểu với
 * sale_plan_out_picking.js. Trang gốc chạy trong IIFE nên mở đơn bằng CustomEvent
 * 'sale_plan:open_order' (trang gốc nghe và gọi openOrderFromNotification).
 * Gỡ tính năng = xoá file này + thẻ <script src> + listener đó + controller cùng tên.
 */
(function () {
"use strict";

var SEARCH_URL = '/api/sale_plan/search_messages';
var ALIAS_URL = '/api/sale_plan/mention_aliases';
var PAGE_SIZE = 30;

// Giá trị period do backend quy đổi ra ngày (services/message_period_utils.py);
// ở đây chỉ là nhãn hiển thị.
var PERIODS = [
    ['', 'Mọi lúc'],
    ['today', 'Hôm nay'],
    ['yesterday', 'Hôm qua'],
    ['7d', '7 ngày qua'],
    ['30d', '30 ngày qua'],
    ['custom', 'Chọn ngày...'],
];

var st = {
    open: false,
    search: '',
    aliases: [],          // alias đã chọn (đã chuẩn hoá chữ thường)
    aliasRows: null,      // null = chưa nạp
    period: '',
    dateFrom: '',
    dateTo: '',
    results: [],
    hasMore: false,
    nextOffset: 0,
    loading: false,
    seq: 0,
    debounce: null,
};

/* ── Tiện ích nhỏ (trang gốc có sẵn nhưng nằm trong IIFE khác) ────────────── */

function esc(value) {
    return String(value === null || value === undefined ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

/** Escape rồi tô <mark> các chỗ khớp từ khoá (không phân biệt hoa thường). */
function highlight(text, term) {
    var safe = esc(text);
    if (!term) return safe;
    var pattern = esc(term).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return safe.replace(new RegExp(pattern, 'gi'), function (m) { return '<mark>' + m + '</mark>'; });
}

function callJson(url, params) {
    return fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: params || {} }),
    }).then(function (res) {
        return res.json();
    }).then(function (payload) {
        return (payload && payload.result) || { status: 'error', message: 'Không đọc được phản hồi.' };
    });
}

function el(id) {
    return document.getElementById(id);
}

/* ── CSS (prefix spms- để không đụng style của trang) ─────────────────────── */

function injectStyles() {
    if (el('spms-styles')) return;
    var css = ''
        + '#spms-button{border:1px solid rgba(255,255,255,.18);background:rgba(255,255,255,.08);color:#fff;border-radius:6px;padding:6px 10px;font-size:.78rem;font-weight:700;line-height:1;display:inline-flex;align-items:center;gap:7px}'
        + '#spms-button.active{background:#4f46e5;border-color:#818cf8}'
        + '#spms-panel{position:fixed;top:0;right:0;bottom:0;width:420px;max-width:100vw;background:#fff;z-index:1060;box-shadow:-8px 0 24px rgba(15,23,42,.18);display:none;flex-direction:column}'
        + '#spms-panel.open{display:flex}'
        + '.spms-head{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;background:#4f46e5;color:#fff;font-weight:700}'
        + '.spms-head button{background:none;border:0;color:#fff;font-size:1.1rem;line-height:1}'
        + '.spms-filters{padding:10px;border-bottom:1px solid #e2e8f0}'
        + '.spms-row{display:flex;gap:6px;align-items:center;margin-top:6px}'
        + '.spms-chip{display:inline-flex;align-items:center;gap:4px;background:#4f46e5;color:#fff;border-radius:999px;padding:1px 8px;font-size:.72rem}'
        + '.spms-chip i{cursor:pointer}'
        + '.spms-status{font-size:.72rem;color:#64748b;margin-top:6px;display:flex;justify-content:space-between}'
        + '.spms-status a{color:#64748b;text-decoration:none;cursor:pointer}'
        + '#spms-list{flex:1 1 auto;min-height:0;overflow:auto;background:#f8fafc}'
        + '.spms-item{display:block;width:100%;text-align:left;border:0;border-bottom:1px solid #e2e8f0;background:#fff;padding:10px 12px}'
        + '.spms-item:hover{background:#eef2ff}'
        + '.spms-so{font-weight:700;color:#1d4ed8}'
        + '.spms-meta{font-size:.75rem;color:#64748b;margin:2px 0}'
        + '.spms-body{font-size:.8rem;color:#0f172a;white-space:normal;word-break:break-word;line-height:1.35}'
        + '.spms-body mark{padding:0 1px;background:#fde68a}'
        + '.spms-empty{padding:28px 12px;text-align:center;color:#94a3b8;font-size:.85rem}';
    var style = document.createElement('style');
    style.id = 'spms-styles';
    style.textContent = css;
    document.head.appendChild(style);
}

/* ── Khung panel + nút navbar ─────────────────────────────────────────────── */

function periodOptionsHtml() {
    return PERIODS.map(function (p) {
        return '<option value="' + p[0] + '">' + esc(p[1]) + '</option>';
    }).join('');
}

function buildPanel() {
    var panel = document.createElement('div');
    panel.id = 'spms-panel';
    panel.innerHTML = ''
        + '<div class="spms-head"><span><i class="fa fa-comments me-2"></i>Tìm tin nhắn</span>'
        + '<button type="button" id="spms-close" title="Đóng">&times;</button></div>'
        + '<div class="spms-filters">'
        + '  <div class="input-group input-group-sm">'
        + '    <span class="input-group-text bg-white"><i class="fa fa-search text-muted"></i></span>'
        + '    <input id="spms-q" type="text" class="form-control" placeholder="Nội dung tin, mã đơn, khách, người gửi..."/>'
        + '  </div>'
        + '  <div class="spms-row">'
        + '    <select id="spms-alias" class="form-select form-select-sm" style="flex:1 1 0;min-width:0" title="Lọc tin có nhắc tên (@alias)">'
        + '      <option value="">@ Nhắc tên...</option></select>'
        + '    <select id="spms-period" class="form-select form-select-sm" style="flex:0 0 auto;width:auto" title="Thời gian tin nhắn">'
        +        periodOptionsHtml() + '</select>'
        + '  </div>'
        + '  <div class="spms-row" id="spms-dates" style="display:none">'
        + '    <input id="spms-from" type="date" class="form-control form-control-sm" title="Từ ngày"/>'
        + '    <span class="text-muted">–</span>'
        + '    <input id="spms-to" type="date" class="form-control form-control-sm" title="Đến ngày"/>'
        + '  </div>'
        + '  <div class="spms-row flex-wrap" id="spms-chips" style="display:none"></div>'
        + '  <div class="spms-status"><span id="spms-count"></span><a id="spms-clear" style="display:none"><i class="fa fa-times me-1"></i>Xóa lọc</a></div>'
        + '</div>'
        + '<div id="spms-list"></div>';
    document.body.appendChild(panel);
}

/** Chèn nút cạnh chuông thông báo; navbar đổi cấu trúc thì gắn cuối navbar. */
function buildButton() {
    var li = document.createElement('li');
    li.className = 'nav-item ms-lg-2 d-flex align-items-center';
    li.innerHTML = '<button id="spms-button" type="button" title="Tìm trong tin nhắn các đơn">'
        + '<i class="fa fa-comments"></i><span>Tìm tin nhắn</span></button>';
    var bellItem = document.querySelector('.mention-noti-wrap');
    if (bellItem && bellItem.parentNode) {
        bellItem.parentNode.insertBefore(li, bellItem);
        return;
    }
    var nav = document.querySelector('#nav1 .navbar-nav');
    if (nav) nav.appendChild(li);
}

/* ── Render ───────────────────────────────────────────────────────────────── */

function aliasRows() {
    var rows = (st.aliasRows || []).slice();
    st.aliases.forEach(function (alias) {
        if (!rows.some(function (r) { return r.alias === alias; })) {
            rows.push({ alias: alias, display_alias: alias, user_name: '' });
        }
    });
    return rows;
}

function renderAliasControls() {
    var rows = aliasRows();
    el('spms-alias').innerHTML = '<option value="">@ Nhắc tên...</option>' + rows.map(function (r) {
        var mark = st.aliases.indexOf(r.alias) >= 0 ? '✓ ' : '';
        var who = r.user_name ? ' — ' + esc(r.user_name) : '';
        return '<option value="' + esc(r.alias) + '">' + mark + '@' + esc(r.display_alias) + who + '</option>';
    }).join('');
    var chips = el('spms-chips');
    chips.style.display = st.aliases.length ? '' : 'none';
    chips.innerHTML = rows.filter(function (r) { return st.aliases.indexOf(r.alias) >= 0; }).map(function (r) {
        return '<span class="spms-chip" title="' + esc(r.user_name) + '">@' + esc(r.display_alias)
            + '<i class="fa fa-times" data-alias="' + esc(r.alias) + '" title="Bỏ alias này"></i></span>';
    }).join('');
}

function periodParams() {
    if (st.period === 'custom' && !st.dateFrom && !st.dateTo) {
        return { period: '', date_from: '', date_to: '' };
    }
    return {
        period: st.period,
        date_from: st.period === 'custom' ? st.dateFrom : '',
        date_to: st.period === 'custom' ? st.dateTo : '',
    };
}

function hasFilters() {
    return !!(st.search.trim() || st.aliases.length || periodParams().period);
}

function renderList() {
    var list = el('spms-list');
    el('spms-clear').style.display = hasFilters() ? '' : 'none';
    if (!hasFilters()) {
        el('spms-count').textContent = '';
        list.innerHTML = '<div class="spms-empty"><i class="fa fa-comments fa-2x mb-2 d-block"></i>'
            + 'Gõ từ khoá, chọn @nhắc tên hoặc thời gian để tìm trong mọi tin nhắn của đơn.</div>';
        return;
    }
    if (st.loading && !st.results.length) {
        el('spms-count').textContent = 'Đang tìm...';
        list.innerHTML = '<div class="spms-empty"><i class="fa fa-spinner fa-spin fa-2x"></i></div>';
        return;
    }
    el('spms-count').textContent = st.results.length + ' tin khớp' + (st.hasMore ? ', còn nữa' : '');
    if (!st.results.length) {
        list.innerHTML = '<div class="spms-empty">Không tìm thấy tin nhắn nào khớp.</div>';
        return;
    }
    var term = st.search.trim();
    var html = st.results.map(function (m) {
        return '<button type="button" class="spms-item" data-so-id="' + esc(m.sale_order_id)
            + '" data-so-name="' + esc(m.so_name) + '">'
            + '<div class="d-flex justify-content-between"><span class="spms-so">' + highlight(m.so_name, term) + '</span>'
            + '<span class="spms-meta" title="' + esc(m.date_full) + '"><i class="fa fa-clock-o me-1"></i>' + esc(m.date) + '</span></div>'
            + '<div class="spms-meta"><i class="fa fa-user me-1"></i>' + highlight(m.author || 'Khách hàng', term)
            + (m.attachment_count ? ' · <i class="fa fa-paperclip"></i> ' + esc(m.attachment_count) : '') + '</div>'
            + (m.preview ? '<div class="spms-body">' + highlight(m.preview, term) + '</div>' : '')
            + '</button>';
    }).join('');
    if (st.hasMore) {
        html += '<div class="p-2 text-center"><button type="button" id="spms-more" class="btn btn-sm btn-outline-secondary"'
            + (st.loading ? ' disabled' : '') + '>'
            + (st.loading ? '<i class="fa fa-spinner fa-spin me-1"></i>Đang tải...' : 'Tải thêm tin cũ hơn')
            + '</button></div>';
    }
    list.innerHTML = html;
}

/* ── Gọi API ──────────────────────────────────────────────────────────────── */

function loadAliases() {
    if (st.aliasRows) return;
    st.aliasRows = [];
    callJson(ALIAS_URL, {}).then(function (res) {
        st.aliasRows = res.status === 'success' ? (res.aliases || []) : [];
        renderAliasControls();
    }).catch(function () {
        st.aliasRows = null;  // cho phép thử lại ở lần mở panel sau
    });
}

/** reset = true: tìm lại từ đầu; false: nối trang kế (offset do backend trả). */
function runSearch(reset) {
    if (!hasFilters()) {
        st.results = [];
        st.hasMore = false;
        st.loading = false;
        renderList();
        return;
    }
    st.seq += 1;
    var seq = st.seq;
    st.loading = true;
    if (reset) st.results = [];
    renderList();
    var params = periodParams();
    params.search = st.search.trim();
    params.aliases = st.aliases.slice();
    params.limit = PAGE_SIZE;
    params.offset = reset ? 0 : st.nextOffset;
    callJson(SEARCH_URL, params).then(function (res) {
        if (seq !== st.seq) return;  // đã có lần tìm mới hơn
        if (res.status !== 'success') throw new Error(res.message || 'error');
        st.results = st.results.concat(res.messages || []);
        st.hasMore = !!res.has_more;
        st.nextOffset = res.next_offset || 0;
    }).catch(function (err) {
        if (seq !== st.seq) return;
        console.warn('sale_plan search_messages failed', err);
        st.hasMore = false;
        el('spms-list').innerHTML = '<div class="spms-empty text-danger">Không tìm được tin nhắn, thử lại sau.</div>';
        st.loading = false;
        return 'failed';
    }).then(function (failed) {
        if (seq !== st.seq || failed) return;
        st.loading = false;
        renderList();
    });
}

/* ── Sự kiện ──────────────────────────────────────────────────────────────── */

function setOpen(open) {
    st.open = open;
    el('spms-panel').classList.toggle('open', open);
    el('spms-button').classList.toggle('active', open);
    if (open) {
        loadAliases();
        renderAliasControls();
        renderList();
        el('spms-q').focus();
    }
}

function toggleAlias(alias) {
    var idx = st.aliases.indexOf(alias);
    if (idx >= 0) st.aliases.splice(idx, 1); else st.aliases.push(alias);
    renderAliasControls();
    runSearch(true);
}

function clearFilters() {
    st.search = '';
    st.aliases = [];
    st.period = '';
    st.dateFrom = '';
    st.dateTo = '';
    el('spms-q').value = '';
    el('spms-period').value = '';
    el('spms-from').value = '';
    el('spms-to').value = '';
    el('spms-dates').style.display = 'none';
    renderAliasControls();
    runSearch(true);
}

function bindEvents() {
    el('spms-button').addEventListener('click', function () { setOpen(!st.open); });
    el('spms-close').addEventListener('click', function () { setOpen(false); });
    el('spms-q').addEventListener('input', function (ev) {
        st.search = ev.target.value;
        clearTimeout(st.debounce);
        st.debounce = setTimeout(function () { runSearch(true); }, 400);
    });
    el('spms-alias').addEventListener('change', function (ev) {
        var alias = ev.target.value;
        ev.target.value = '';
        if (alias) toggleAlias(alias);
    });
    el('spms-period').addEventListener('change', function (ev) {
        st.period = ev.target.value;
        var custom = st.period === 'custom';
        el('spms-dates').style.display = custom ? '' : 'none';
        if (!custom) {
            st.dateFrom = st.dateTo = '';
            el('spms-from').value = el('spms-to').value = '';
        }
        runSearch(true);
    });
    el('spms-from').addEventListener('change', function (ev) { st.dateFrom = ev.target.value || ''; runSearch(true); });
    el('spms-to').addEventListener('change', function (ev) { st.dateTo = ev.target.value || ''; runSearch(true); });
    el('spms-chips').addEventListener('click', function (ev) {
        var icon = ev.target.closest('[data-alias]');
        if (icon) toggleAlias(icon.getAttribute('data-alias'));
    });
    el('spms-clear').addEventListener('click', clearFilters);
    el('spms-list').addEventListener('click', function (ev) {
        if (ev.target.closest('#spms-more')) {
            if (!st.loading) runSearch(false);
            return;
        }
        var item = ev.target.closest('.spms-item');
        if (!item) return;
        setOpen(false);
        document.dispatchEvent(new CustomEvent('sale_plan:open_order', {
            detail: { so_id: item.getAttribute('data-so-id'), so_name: item.getAttribute('data-so-name') },
        }));
    });
    document.addEventListener('keydown', function (ev) {
        if (ev.key === 'Escape' && st.open) setOpen(false);
    });
}

function init() {
    injectStyles();
    buildPanel();
    buildButton();
    if (!el('spms-button')) return;
    bindEvents();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
})();
