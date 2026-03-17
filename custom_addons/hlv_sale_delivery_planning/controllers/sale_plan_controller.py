# -*- coding: utf-8 -*-
import logging
import time
from collections import defaultdict
from markupsafe import Markup
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

SESSION_KEY_OK = "inv_pw_ok"
PW_PARAM_KEY = "website_public_inventory_18.search_password"

_FAIL_LOG = defaultdict(list)
_RL_MAX = 5
_RL_WINDOW = 600


def _is_rate_limited(ip):
    now = time.time()
    recent = [t for t in _FAIL_LOG[ip] if now - t < _RL_WINDOW]
    _FAIL_LOG[ip] = recent
    return len(recent) >= _RL_MAX


def _record_failure(ip):
    _FAIL_LOG[ip].append(time.time())


_H = [("Content-Type", "text/html; charset=utf-8")]

_ERR_PW = '<div class="alert alert-danger mb-3">Mật khẩu không đúng.</div>'
_ERR_RATE = '<div class="alert alert-danger mb-3">Quá nhiều lần thử sai. Vui lòng thử lại sau 10 phút.</div>'

_LOGIN = """<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"/>
<title>Tình trạng Đơn hàng</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"/>
</head>
<body class="bg-light d-flex align-items-center justify-content-center" style="min-height:100vh">
<div class="card shadow p-4" style="max-width:400px;width:100%;border-radius:4px">
  <h4 class="fw-bold text-center text-primary mb-3">&#128666; Tình trạng Đơn hàng</h4>
  {err}
  <form method="post" action="/sale_plan">
    <input type="hidden" name="csrf_token" value="{csrf}"/>
    <label class="form-label fw-bold">Mật khẩu</label>
    <input type="password" name="inv_password" class="form-control form-control-lg mb-3" autofocus required/>
    <button type="submit" class="btn btn-primary w-100 btn-lg">Xác nhận</button>
  </form>
</div></body></html>"""

_PAGE = r"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"/>
<title>Tình trạng đơn hàng</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/>
<style>
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#f0f2f5}
.card,.form-control,.form-select,.btn,.badge,.list-group-item,.alert,.modal-content,
.input-group-text,.dropdown-menu{border-radius:3px!important}
/* KPI row 1 - colored background cards */
.kpi-main{padding:18px 20px;color:#fff;position:relative;overflow:hidden;border:0;transition:.2s;box-shadow:0 2px 8px rgba(0,0,0,.15)}
.kpi-main:hover{opacity:.92;box-shadow:0 4px 16px rgba(0,0,0,.2);transform:translateY(-1px)}
.kpi-main .kpi-icon{position:absolute;right:14px;top:50%;transform:translateY(-50%);font-size:2.4rem;opacity:.25}
.kpi-main .kpi-label{font-size:.78rem;text-transform:uppercase;font-weight:600;letter-spacing:.3px;opacity:.9}
.kpi-main .kpi-val{font-size:2rem;font-weight:800;line-height:1.1}
.kpi-bg-total{background:linear-gradient(135deg,#4a5568,#2d3748)}
.kpi-bg-ready{background:linear-gradient(135deg,#38a169,#276749)}
.kpi-bg-partial{background:linear-gradient(135deg,#d69e2e,#b7791f)}
.kpi-bg-out{background:linear-gradient(135deg,#e53e3e,#c53030)}
/* KPI row 2 - packing with circle icons */
.kpi-pack{padding:14px 16px;border:1px solid #e2e8f0;cursor:pointer;transition:.2s;display:flex;align-items:center;gap:14px;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.kpi-pack:hover{box-shadow:0 3px 12px rgba(0,0,0,.1);border-color:#cbd5e0;transform:translateY(-1px)}
.kpi-pack.active{border-color:#3182ce;box-shadow:0 0 0 2px rgba(49,130,206,.25);background:#ebf8ff}
.kpi-pack-icon{width:44px;height:44px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:1.1rem;flex-shrink:0}
.kpi-pack .kpi-pack-label{font-size:.75rem;color:#718096;text-transform:uppercase;font-weight:600;letter-spacing:.3px}
.kpi-pack .kpi-pack-val{justify-content: center;align-items: center;text-align: center;width: 100%;font-size:1.6rem;font-weight:700;line-height:1.2;color:#2d3748;}
/* Badges */
.badge-del-pending{background:#6c757d;color:#fff}
.badge-del-partial{background:#ffc107;color:#000}
.badge-del-full{background:#198754;color:#fff}
.badge-stk-ready{background:#0d6efd;color:#fff}
.badge-stk-partial{background:#ffc107;color:#000}
.badge-stk-out{background:#dc3545;color:#fff}
.badge-pack-waiting{background:#6c757d;color:#fff}
.badge-pack-unpacked{background:#ffc107;color:#000}
.badge-pack-done{background:#198754;color:#fff}
.badge-po-pending{background:#6c757d;color:#fff}
.badge-po-partial{background:#0dcaf0;color:#000}
.badge-po-full{background:#198754;color:#fff}
.cursor-pointer{cursor:pointer}
/* Filter chips */
.filter-chip{font-size:.82rem;padding:5px 8px 5px 10px;display:inline-flex;align-items:center;gap:6px;cursor:default}
.filter-chip .chip-x{background:none;border:none;color:#fff;font-size:1rem;line-height:1;padding:0 2px;cursor:pointer;opacity:.8}
.filter-chip .chip-x:hover{opacity:1}
/* Kanban */
.kanban-col{min-width:320px;max-width:420px;flex:1}
.kanban-col .card-header{font-size:.85rem}
/* Cards */
.so-card{border-width:2px!important;transition:.1s}
.so-card:hover{box-shadow:0 3px 10px rgba(0,0,0,.1)}
/* Drawer */
#drawer{position:fixed;top:0;right:-820px;width:800px;height:100vh;background:#fff;
  box-shadow:-4px 0 24px rgba(0,0,0,.15);z-index:1060;transition:right .3s;overflow-y:auto}
#drawer.open{right:0}
#drawer-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.3);z-index:1055}
#drawer-overlay.open{display:block}
/* Drawer table */
.table-lines td,.table-lines th{font-size:.85rem;vertical-align:middle}
.table-lines thead th{background:#f7fafc;color:#4a5568;font-weight:600;text-transform:uppercase;font-size:.75rem;letter-spacing:.3px;padding:10px 8px;border-bottom:2px solid #e2e8f0}
.table-lines td{padding:8px;border-color:#cccc}
.table-lines tbody tr:hover{background:#f7fafc}
.table-lines .cell-packed-full{color:#198754;font-weight:700}
.table-lines .cell-packed-partial{color:#0dcaf0;font-weight:700}
.table-lines .cell-packed-zero{color:#adb5bd}
.table-lines .cell-stock-ok{color:#198754;font-weight:700}
.table-lines .cell-stock-zero{color:#dc3545}
.table-lines .cell-shortage{color:#dc3545;font-weight:700}
.table-lines .cell-delivered{color:#0d6efd}
.row-pending{background:#fffbeb}
.row-delivered{background:#f0fdf4}
/* Kanban col load more */
.btn-col-more{font-size:.8rem;padding:6px 0;width:100%;background:#f7fafc;border:1px dashed #cbd5e0;color:#4a5568;cursor:pointer;transition:.15s;font-weight:600}
.btn-col-more:hover{background:#edf2f7;border-color:#a0aec0;color:#2d3748}
/* Loading */
.loading-overlay{position:fixed;inset:0;background:rgba(255,255,255,.6);z-index:2000;
  display:flex;align-items:center;justify-content:center}
.loading-overlay .spinner-border{width:3rem;height:3rem}
/* Load more */
#btn-load-more{font-weight:600;padding:4px 32px}
@media(max-width:768px){#drawer{width:100%} .kanban-col{min-width:100%}}
/* Report button */
.btn-report{font-size:.72rem;padding:2px 7px;border:1px solid #fed7d7;color:#c53030;background:#fff5f5;border-radius:3px;cursor:pointer;transition:.15s;line-height:1.4}
.btn-report:hover{background:#fed7d7;border-color:#c53030}
/* Report modal */
#report-modal{display:none;position:fixed;inset:0;z-index:2000;background:rgba(0,0,0,.5);align-items:center;justify-content:center}
#report-modal .rmod-card{background:#fff;max-width:440px;width:90%;border-radius:4px;padding:24px;box-shadow:0 8px 32px rgba(0,0,0,.2)}
</style>
</head><body>
<div id="loading" class="loading-overlay d-none"><div class="spinner-border text-primary"></div></div>
<nav class="navbar navbar-expand-lg navbar-dark bg-primary mb-3" style="border-radius:0!important">
<div class="container-fluid">
  <a class="navbar-brand fw-bold" href="/sale_plan">&#128666; Tình trạng đơn hàng</a>
  <button class="navbar-toggler" data-bs-toggle="collapse" data-bs-target="#nav1"><span class="navbar-toggler-icon"></span></button>
  <div class="collapse navbar-collapse" id="nav1">
    <ul class="navbar-nav ms-auto">
      <li class="nav-item"><a class="nav-link" href="/search_stock">Tồn kho</a></li>
      <li class="nav-item"><a class="nav-link" href="/search_order">Chứng từ mua</a></li>
      <li class="nav-item"><a class="nav-link active" href="/sale_plan">Tình trạng đơn</a></li>
      <li class="nav-item"><a class="nav-link" href="/search_invoice">Hóa đơn MISA</a></li>
    </ul>
  </div>
</div></nav>
<div class="container-fluid px-3">
<!-- KPI row 1 -->
<div class="row g-2 mb-2">
  <div class="col-6 col-md-3"><div class="card kpi-main kpi-bg-total"><div class="kpi-label">Đơn hàng</div><div class="kpi-val" id="kpi-total">0</div><i class="fa fa-boxes-stacked kpi-icon"></i></div></div>
  <div class="col-6 col-md-3"><div class="card kpi-main kpi-bg-ready"><div class="kpi-label">Sẵn sàng xuất đủ</div><div class="kpi-val" id="kpi-ready">0</div><i class="fa fa-circle-check kpi-icon"></i></div></div>
  <div class="col-6 col-md-3"><div class="card kpi-main kpi-bg-partial"><div class="kpi-label">Có hàng 1 phần</div><div class="kpi-val" id="kpi-partial">0</div><i class="fa fa-exclamation-circle kpi-icon"></i></div></div>
  <div class="col-6 col-md-3"><div class="card kpi-main kpi-bg-out"><div class="kpi-label">Chưa có hàng / Thiếu</div><div class="kpi-val" id="kpi-outstock">0</div><i class="fa fa-xmark-circle kpi-icon"></i></div></div>
</div>
<!-- KPI row 2 - packing -->
<div class="row g-2 mb-3">
  <div class="col-md-4"><div class="card kpi-pack" id="kpi-pack-waiting" data-filter="waiting_stock">
    <div class="kpi-pack-icon" style="background:#fed7d7;color:#c53030"><i class="fa fa-circle-xmark"></i></div>
    <div><div class="kpi-pack-label">Không có hàng đóng</div><div class="kpi-pack-val" id="kpi-pw">0</div></div>
  </div></div>
  <div class="col-md-4"><div class="card kpi-pack" id="kpi-pack-unpacked" data-filter="unpacked">
    <div class="kpi-pack-icon" style="background:#fefcbf;color:#b7791f"><i class="fa fa-box-open"></i></div>
    <div><div class="kpi-pack-label">Có hàng chưa đóng gói</div><div class="kpi-pack-val" id="kpi-pu">0</div></div>
  </div></div>
  <div class="col-md-4"><div class="card kpi-pack" id="kpi-pack-done" data-filter="fully_packed">
    <div class="kpi-pack-icon" style="background:#c6f6d5;color:#276749"><i class="fa fa-circle-check"></i></div>
    <div><div class="kpi-pack-label">Đã đóng gói đủ</div><div class="kpi-pack-val" id="kpi-pf">0</div></div>
  </div></div>
</div>
<!-- Active Filters -->
<div id="active-filters" class="mb-2 d-none d-flex flex-wrap gap-1 align-items-center"></div>
<!-- Filters -->
<div class="card mb-3"><div class="card-body py-2">
<div class="row g-2 mb-2">
  <div class="col-md-2"><label class="form-label small mb-0">Tìm Kiếm</label><input id="f-q" class="form-control form-control-sm" placeholder="SO / Khách hàng..."/></div>
  <div class="col-md-2"><label class="form-label small mb-0">Kho Cung Cấp</label><select id="f-wh" class="form-select form-select-sm"><option value="all">Tất cả</option></select></div>
  <div class="col-md-1"><label class="form-label small mb-0">Giao từ</label><input type="date" id="f-date-from" class="form-control form-control-sm"/></div>
  <div class="col-md-1"><label class="form-label small mb-0">Giao đến</label><input type="date" id="f-date-to" class="form-control form-control-sm"/></div>
  <div class="col-md-2"><label class="form-label small mb-0">Tiến Độ Giao</label>
    <select id="f-del" class="form-select form-select-sm">
      <option value="pending_partial" selected>Chưa giao &amp; Giao 1 phần</option>
      <option value="all">Tất cả</option><option value="pending">Chưa giao</option>
      <option value="partial">Giao 1 phần</option><option value="full">Đã giao đủ</option>
    </select></div>
  <div class="col-md-2"><label class="form-label small mb-0">Tình Trạng Kho</label>
    <select id="f-stk" class="form-select form-select-sm">
      <option value="all">Tất cả</option><option value="ready">Đủ hàng</option>
      <option value="partial_ready">Có hàng 1 phần</option><option value="out_of_stock">Không có hàng</option>
    </select></div>
  <div class="col-md-2 d-flex align-items-end"><button id="btn-filter" class="btn btn-primary btn-sm w-100"><i class="fa fa-search"></i> Lọc</button></div>
</div>
<div class="row g-2">
  <div class="col-md-2"><label class="form-label small mb-0">Đóng Gói</label>
    <select id="f-pack" class="form-select form-select-sm">
      <option value="all">Tất cả</option><option value="waiting_stock">Không có hàng đóng</option>
      <option value="unpacked">Có hàng chưa đóng gói</option><option value="fully_packed">Đã đóng gói đủ</option>
    </select></div>
  <div class="col-md-2"><label class="form-label small mb-0">Mã NV MISA</label><input id="f-saler" class="form-control form-control-sm" placeholder="VD: NV001"/></div>
  <div class="col-md-2"><label class="form-label small mb-0">HTGH</label><input id="f-htgh" class="form-control form-control-sm" placeholder="VD: NHờ KHO..."/></div>
  <div class="col-md-2"><label class="form-label small mb-0">Loại vận chuyển</label>
    <select id="f-dtype" class="form-select form-select-sm">
      <option value="all">Tất cả</option>
      <option value="HLV vận chuyển">HLV vận chuyển</option>
      <option value="GHN">GHN</option>
      <option value="J&T">J&amp;T</option>
    </select></div>
  <div class="col-md-2"><label class="form-label small mb-0">Nhận hàng từ</label><input type="date" id="f-po-date-from" class="form-control form-control-sm"/></div>
  <div class="col-md-2"><label class="form-label small mb-0">Nhận hàng đến</label><input type="date" id="f-po-date-to" class="form-control form-control-sm"/></div>
  <div class="col-md-2"><label class="form-label small mb-0">Tag <small class="text-muted">(Ctrl+click chọn nhiều)</small></label><select id="f-tag" multiple class="form-select form-select-sm" style="max-height:90px"></select></div>

  <div class="col-md-2"><label class="form-label small mb-0">Trạng Thái (Mua hàng)</label>
  
    <select id="f-po-status" class="form-select form-select-sm">
      <option value="all">Tất cả</option><option value="pending">Chưa nhận hàng</option>
      <option value="partial">Nhận 1 phần</option><option value="full">Đã nhận đủ</option>
    </select></div>
  </div>

</div></div>
<!-- View toggle -->
<div class="d-flex justify-content-between align-items-center mb-2 flex-wrap gap-2">
  <div class="d-flex gap-1 flex-wrap align-items-center">
    <span class="text-muted small fw-bold me-1"><i class="fa fa-layer-group"></i> PHÂN NHÓM:</span>
    <button id="grp-packing" class="btn btn-sm btn-outline-primary active">&#128230; Đóng gói</button>
    <button id="grp-delivery" class="btn btn-sm btn-outline-primary">&#128666; Tiến độ giao</button>
    <button id="grp-stock" class="btn btn-sm btn-outline-primary">&#128230; Tình trạng kho</button>
  </div>
  <div class="d-flex align-items-center gap-2">
    <button id="btn-refresh" class="btn btn-sm btn-outline-success" title="Làm mới"><i class="fa fa-refresh"></i> Làm mới</button>
    <button id="btn-kanban" class="btn btn-sm btn-primary"><i class="fa fa-th"></i> Kanban</button>
    <button id="btn-list" class="btn btn-sm btn-outline-secondary"><i class="fa fa-list"></i> Danh sách</button>
    <span class="vr"></span>
    <button id="btn-load-more" class="btn btn-sm btn-outline-primary d-none"><i class="fa fa-plus"></i> Tải thêm 200</button>
    <span class="badge bg-primary" style="font-size:.85rem;padding:9px 12px" id="count-info">0 / 0 đơn hàng</span>
  </div>
</div>
<!-- Kanban -->
<div id="kanban-view" class="d-flex gap-3 overflow-auto pb-3"></div>
<!-- List -->
<div id="list-view" class="d-none">
<div class="table-responsive"><table class="table table-hover table-sm table-bordered table-lines align-middle">
<thead class="table-light"><tr>
  <th>Đơn hàng</th><th>Khách hàng</th><th>Kho</th><th>Ngày đặt</th>
  <th>Giao dự kiến</th><th>Tổng tiền</th><th>Giao hàng</th><th>Tồn kho</th><th>Đóng kiện</th>
</tr></thead><tbody id="tbl-body"></tbody>
</table></div></div>
</div>
<!-- Drawer overlay -->
<div id="drawer-overlay"></div>
<div id="drawer">
  <div class="p-3 border-bottom d-flex justify-content-between align-items-center bg-primary text-white">
    <h5 class="mb-0" id="dr-title"></h5>
    <button id="dr-close" class="btn btn-sm btn-light">&times;</button>
  </div>
  <div id="dr-body" class="p-3"></div>
  <div class="p-3 border-top bg-light fw-bold" id="dr-footer"></div>
</div>
<!-- Report modal -->
<div id="report-modal">
  <div class="rmod-card">
    <h6 class="fw-bold mb-1"><i class="fa fa-flag text-danger me-1"></i> Báo cáo đơn hàng</h6>
    <p class="text-muted small mb-3" id="report-so-name"></p>
    <textarea id="report-reason" class="form-control mb-3" rows="3" placeholder="Mô tả vấn đề (tùy chọn)..."></textarea>
    <div class="d-flex gap-2">
      <button class="btn btn-danger btn-sm flex-fill" id="report-submit"><i class="fa fa-flag me-1"></i>Gửi báo cáo</button>
      <button class="btn btn-outline-secondary btn-sm" id="report-cancel">Hủy</button>
    </div>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
(function(){
"use strict";
var S={limit:250,total:0,viewMode:'kanban',kanbanGroupBy:'packing_status',
  orders:[],warehouses:[],stats:{},whLoaded:false,kanbanColPageSize:{},reportedIds:{},tagsLoaded:false};

var DL={unshipped:'CHƯA GIAO',pending:'CHƯA GIAO',partial:'Giao 1 phần',full:'Đã giao đủ'};
var DC={unshipped:'badge-del-pending',pending:'badge-del-pending',partial:'badge-del-partial',full:'badge-del-full'};
var SL={ready:'Đủ hàng xuất',partial_ready:'Có hàng 1 phần',out_of_stock:'Không có hàng'};
var SC={ready:'badge-stk-ready',partial_ready:'badge-stk-partial',out_of_stock:'badge-stk-out'};
var PL={waiting_stock:'Không Có Hàng Đóng',unpacked:'Có Hàng Chưa Đóng Gói',fully_packed:'Đã Đóng Gói Đủ'};
var PC={waiting_stock:'badge-pack-waiting',unpacked:'badge-pack-unpacked',fully_packed:'badge-pack-done'};
var POL={pending:'Chưa nhận',partial:'Nhận 1 phần',full:'Đã nhận đủ'};
var POC={pending:'badge-po-pending',partial:'badge-po-partial',full:'badge-po-full'};

function $(id){return document.getElementById(id)}
function fd(s){if(!s)return'';var d=new Date(s);if(isNaN(d))return s;return('0'+d.getDate()).slice(-2)+'/'+('0'+(d.getMonth()+1)).slice(-2)+'/'+d.getFullYear()}
function fm(v){return(v||0).toLocaleString('vi-VN')+'₫'}
function fq(v){var n=parseFloat(v)||0;return n%1===0?n.toLocaleString('vi-VN'):n.toLocaleString('vi-VN',{minimumFractionDigits:0,maximumFractionDigits:2})}
function b(cls,label){return'<span class="badge '+cls+' me-1">'+label+'</span>'}
function esc(s){if(!s)return'';var d=document.createElement('div');d.textContent=s;return d.innerHTML}
function gv(id){var e=$(id);return e?e.value:'';}
function showLoading(){var l=$('loading');if(l)l.classList.remove('d-none');}
function hideLoading(){var l=$('loading');if(l)l.classList.add('d-none');}
function getTagIds(){var e=$('f-tag');if(!e)return'';return Array.from(e.selectedOptions).map(function(o){return o.value;}).filter(Boolean).join(',');}
var TAG_BG=['#adb5bd','#dc3545','#fd7e14','#ffc107','#20c997','#6610f2','#d63384','#0d6efd','#6f42c1','#e91e63','#198754','#0dcaf0'];
var TAG_FG=[0,0,0,1,1,0,0,0,0,0,0,1]; // 1=dark text
function tagBadge(tag){var c=tag[2]||0;var bg=TAG_BG[c]||TAG_BG[0];var fg=TAG_FG[c]?'#000':'#fff';return'<span class="badge me-1" style="background-color:'+bg+';color:'+fg+'">'+esc(tag[1])+'</span>';}
function groupLines(lines){
  var map={},order=[];
  lines.forEach(function(l){
    var pid=l.product_id?l.product_id[0]:0;
    if(map[pid]){
      map[pid].product_uom_qty+=l.product_uom_qty||0;
      map[pid].qty_delivered+=l.qty_delivered||0;
      map[pid].qty_reserved_here+=(l.qty_reserved_here||0); // sum reservations across lines
      // qty_warehouse_free: keep first (product-level, same for all lines of same product/wh)
    } else {
      map[pid]={product_id:l.product_id,product_uom_qty:l.product_uom_qty||0,
        qty_delivered:l.qty_delivered||0,qty_packed:l.qty_packed||0,
        qty_available:l.qty_available||0,qty_warehouse_free:l.qty_warehouse_free||0,
        qty_reserved_here:l.qty_reserved_here||0,is_kit:l.is_kit||false};
      order.push(pid);
    }
  });
  return order.map(function(pid){return map[pid];});
}

function partnerName(o){return o.partner_id?o.partner_id[1]:'';}

function load(append){
  showLoading();
  var offset=append?S.orders.length:0;
  var lim=append?200:S.limit;
  var body={search:gv('f-q'),warehouse_id:gv('f-wh'),delivery_status:gv('f-del'),
    stock_status:gv('f-stk'),packing_status:gv('f-pack'),
    date_from:gv('f-date-from'),date_to:gv('f-date-to'),
    po_date_from:gv('f-po-date-from'),po_date_to:gv('f-po-date-to'),
    po_status:gv('f-po-status'),saler_code:gv('f-saler'),
    htgh:gv('f-htgh'),delivery_type:gv('f-dtype'),tag_ids:getTagIds(),
    limit:lim,offset:offset};
  fetch('/api/sale_plan/data',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({jsonrpc:'2.0',method:'call',params:body})})
  .then(function(r){return r.json()})
  .then(function(j){
    hideLoading();
    if(!j.result||j.result.status!=='success'){console.error('API error',j);return;}
    var d=j.result.data;
    if(append){
      S.orders=S.orders.concat(d.orders||[]);
    } else {
      S.orders=d.orders||[];
      S.kanbanColPageSize={};
    }
    S.total=d.total_count||0;
    S.stats=d.dashboard_stats||{};
    if(d.warehouses&&!S.whLoaded){
      var sel=$('f-wh');
      d.warehouses.forEach(function(w){
        var o=document.createElement('option');o.value=w.id;o.textContent=w.name;sel.appendChild(o);
      });
      S.whLoaded=true;
      S.warehouses=d.warehouses;
    }
    if(d.tags&&!S.tagsLoaded){
      var tsel=$('f-tag');
      S.tagsMap={};
      d.tags.forEach(function(t){
        S.tagsMap[t.id]=t;
        var o=document.createElement('option');o.value=t.id;o.textContent=t.name;tsel.appendChild(o);
      });
      S.tagsLoaded=true;
    }
    updKPI();render();updLoadMore();updFilters();
  }).catch(function(e){hideLoading();console.error(e);});
}

function updKPI(){
  var s=S.stats;
  $('kpi-total').textContent=s.total||S.total||0;
  $('kpi-ready').textContent=s.ready||0;
  $('kpi-partial').textContent=s.partial||0;
  $('kpi-outstock').textContent=s.out_of_stock||0;
  $('kpi-pw').textContent=s.packing_waiting||0;
  $('kpi-pu').textContent=s.packing_unpacked||0;
  $('kpi-pf').textContent=s.packing_fully||0;
  // Sync active state trên KPI pack cards với filter hiện tại
  var curPack=gv('f-pack');
  document.querySelectorAll('.kpi-pack').forEach(function(el){el.classList.remove('active');});
  if(curPack&&curPack!=='all'){
    var activeCard=document.querySelector('.kpi-pack[data-filter="'+curPack+'"]');
    if(activeCard)activeCard.classList.add('active');
  }
}

function updLoadMore(){
  var btn=$('btn-load-more');
  var remaining=S.total-S.orders.length;
  if(remaining>0){
    btn.classList.remove('d-none');
    btn.innerHTML='<i class="fa fa-plus"></i> Tải thêm '+(remaining>=200?200:remaining);
  } else {
    btn.classList.add('d-none');
  }
  $('count-info').textContent=S.orders.length+' / '+S.total+' đơn hàng';
}

function render(){
  if(S.viewMode==='kanban') renderKanban(); else renderList();
  $('kanban-view').classList.toggle('d-none',S.viewMode!=='kanban');
  $('list-view').classList.toggle('d-none',S.viewMode!=='list');
  ['grp-packing','grp-delivery','grp-stock'].forEach(function(id){
    $(id).style.display=S.viewMode==='kanban'?'':'none';
  });
}

function renderKanban(){
  var cols,gb=S.kanbanGroupBy;
  if(gb==='packing_status') cols=[
    {key:'waiting_stock',lbl:'KHÔNG CÓ HÀNG ĐÓNG',cls:'text-secondary'},
    {key:'unpacked',lbl:'CÓ HÀNG CHƯA ĐÓNG GÓI',cls:'text-warning'},
    {key:'fully_packed',lbl:'ĐÃ ĐÓNG GÓI ĐỦ',cls:'text-success'}
  ];
  else if(gb==='delivery_status') cols=[
    {key:'unshipped',lbl:'CHƯA GIAO',cls:'text-secondary'},
    {key:'partial',lbl:'GIAO 1 PHẦN',cls:'text-warning'},
    {key:'full',lbl:'ĐÃ GIAO ĐỦ',cls:'text-success'}
  ];
  else cols=[
    {key:'out_of_stock',lbl:'KHÔNG CÓ HÀNG',cls:'text-danger'},
    {key:'partial_ready',lbl:'CÓ HÀNG 1 PHẦN',cls:'text-warning'},
    {key:'ready',lbl:'ĐỦ HÀNG',cls:'text-success'}
  ];

  var wrap=$('kanban-view');wrap.innerHTML='';
  cols.forEach(function(c){
    var field=(gb==='delivery_status')?'real_delivery_status':gb;
    var items=S.orders.filter(function(o){return o[field]===c.key;});
    var pageSize=S.kanbanColPageSize[c.key]||15;
    var visible=items.slice(0,pageSize);
    var remaining=items.length-pageSize;
    var col=document.createElement('div');col.className='kanban-col';
    col.innerHTML='<div class="card"><div class="card-header d-flex justify-content-between align-items-center '+c.cls+' py-2">'
      +'<strong>'+c.lbl+'</strong><span class="badge bg-secondary rounded-pill">'+items.length+'</span></div>'
      +'<div class="card-body p-2 d-flex flex-column gap-2"></div></div>';
    wrap.appendChild(col);
    var body=col.querySelector('.card-body');
    visible.forEach(function(o){
      var card=document.createElement('div');
      card.innerHTML=renderSOCard(o);
      body.appendChild(card.firstChild);
    });
    if(remaining>0){
      var btn=document.createElement('button');
      btn.className='btn-col-more mt-1';
      btn.innerHTML='<i class="fa fa-chevron-down"></i> Tải thêm ('+remaining+' còn lại)';
      btn.setAttribute('data-col-key',c.key);
      body.appendChild(btn);
    }
  });
}

function getCardBorderClass(o){
  var rd=o.real_delivery_status||o.delivery_status;
  if(rd==='full')return'border-success';
  if(o.stock_status==='ready')return'border-primary';
  if(o.stock_status==='partial_ready')return'border-warning';
  return'border-danger';
}

function renderSOCard(o){
  var bc=getCardBorderClass(o);
  var rd=o.real_delivery_status||o.delivery_status;
  var reported=S.reportedIds&&S.reportedIds[o.id];
  var h='<div class="card so-card cursor-pointer '+bc+(reported?' opacity-75':'')+'" data-so-id="'+o.id+'">'
    +'<div class="card-header py-2">'
    +'<div class="d-flex flex-wrap gap-1 mb-1">'
    +b(DC[rd]||'badge-del-pending',DL[rd]||rd)
    +b(SC[o.stock_status]||'badge-stk-out',SL[o.stock_status]||o.stock_status)
    +b(PC[o.packing_status]||'badge-pack-waiting',PL[o.packing_status]||o.packing_status)
    +'</div>'
    +'<h6 class="text-primary fw-bold mb-0">'+esc(o.name)+'</h6>'
    +'<small class="text-muted"><i class="fa fa-user"></i> '+esc(partnerName(o))+'</small>'
    +'</div><div class="card-body py-2">';
  if(o.commitment_date) h+='<small class="text-muted"><i class="fa fa-calendar"></i> '+fd(o.commitment_date)+'</small><br>';
  if(o.x_studio_delivery_type) h+='<small class="text-muted"><i class="fa fa-truck me-1"></i>'+esc(o.x_studio_delivery_type)+'</small><br>';
  if(o.x_studio_htgh) h+='<small class="text-muted"><i class="fa fa-info-circle me-1"></i>'+esc(o.x_studio_htgh)+'</small><br>';
  if(o.misa_shipping_address) h+='<small class="text-muted" style="font-size:.7rem"><i class="fa fa-map-marker me-1 text-danger"></i>'+esc(o.misa_shipping_address)+'</small><br>';
  if(o.tag_ids&&o.tag_ids.length) h+='<div class="mt-1">'+o.tag_ids.map(tagBadge).join('')+'</div>';
  h+='<div class="d-flex justify-content-between align-items-center">'
    +'<span class="fw-bold">'+fm(o.amount_total)+'</span>';
  var pc=o.pos?o.pos.length:0;
  if(pc>0) h+='<span class="badge bg-info text-dark">'+pc+' PO</span>';
  h+='</div>';
  h+='<div class="d-flex justify-content-end mt-2">';
  if(reported){
    h+='<span class="text-muted" style="font-size:.72rem"><i class="fa fa-flag text-danger me-1"></i>Đã báo cáo</span>';
  } else {
    h+='<button class="btn-report" data-so-id="'+o.id+'" data-so-name="'+esc(o.name)+'"><i class="fa fa-flag me-1"></i>Báo cáo</button>';
  }
  h+='</div></div></div>';
  return h;
}

function renderList(){
  var tb=$('tbl-body');tb.innerHTML='';
  S.orders.forEach(function(o){
    var rd=o.real_delivery_status||o.delivery_status;
    var tr=document.createElement('tr');
    tr.className='cursor-pointer';
    tr.setAttribute('data-so-id',o.id);
    var isReported=S.reportedIds&&S.reportedIds[o.id];
    var reportCell=isReported
      ?'<td><span class="text-muted" style="font-size:.72rem"><i class="fa fa-flag text-danger"></i></span></td>'
      :'<td><button class="btn-report" data-so-id="'+o.id+'" data-so-name="'+esc(o.name)+'"><i class="fa fa-flag"></i></button></td>';
    tr.innerHTML='<td class="fw-bold text-primary">'+esc(o.name)+'</td>'
      +'<td>'+esc(partnerName(o))+'</td>'
      +'<td>'+esc(whName(o))+'</td>'
      +'<td>'+fd(o.date_order)+'</td>'
      +'<td>'+fd(o.commitment_date)+'</td>'
      +'<td class="text-end">'+fm(o.amount_total)+'</td>'
      +'<td>'+b(DC[rd]||'',DL[rd]||'')+'</td>'
      +'<td>'+b(SC[o.stock_status]||'',SL[o.stock_status]||'')+'</td>'
      +'<td>'+b(PC[o.packing_status]||'',PL[o.packing_status]||'')+'</td>'
      +reportCell;
    tb.appendChild(tr);
  });
}

function openDrawer(id){
  var o=S.orders.find(function(x){return x.id===id;});
  if(!o)return;
  $('dr-title').textContent=o.name;
  var rd=o.real_delivery_status||o.delivery_status;
  var h='<div class="mb-3">'
    +'<div class="d-flex flex-wrap gap-1 mb-2">'
    +b(DC[rd]||'badge-del-pending',DL[rd]||rd)
    +b(SC[o.stock_status]||'badge-stk-out',SL[o.stock_status]||o.stock_status)
    +b(PC[o.packing_status]||'badge-pack-waiting',PL[o.packing_status]||o.packing_status)
    +'</div>'
    +'<div class="d-flex flex-column gap-2 mt-2 p-3 rounded" style="background:#f7fafc;border:1px solid #e2e8f0">'
    +'<div><i class="fa fa-user text-primary me-2"></i><strong>'+esc(partnerName(o))+'</strong></div>'
    +'<div><i class="fa fa-warehouse text-muted me-2"></i><span class="text-muted">'+esc(whName(o))+'</span></div>'
    +(o.commitment_date?'<div><i class="fa fa-calendar text-muted me-2"></i><span class="text-muted">Hẹn giao: '+fd(o.commitment_date)+'</span></div>':'')
    +(o.x_studio_delivery_type?'<div><i class="fa fa-truck text-muted me-2"></i><span class="text-muted">'+esc(o.x_studio_delivery_type)+'</span></div>':'')
    +(o.x_studio_htgh?'<div><i class="fa fa-info-circle text-muted me-2"></i><span class="text-muted">HTGH: '+esc(o.x_studio_htgh)+'</span></div>':'')
    +(o.misa_shipping_address?'<div><i class="fa fa-map-marker text-muted me-2"></i><span class="text-muted">'+esc(o.misa_shipping_address)+'</span></div>':'')
    +(o.tag_ids&&o.tag_ids.length?'<div><i class="fa fa-tags text-muted me-2"></i>'+o.tag_ids.map(tagBadge).join('')+'</div>':'')
    +'</div>'
    +'</div>';
  h+='<table class="table table-sm table-bordered table-lines"><thead class="table-light"><tr>'
    +'<th>Sản phẩm</th><th class="text-end">Chốt Bán</th><th class="text-end">Đóng Gói</th>'
    +'<th class="text-end">Tồn Kho</th><th class="text-end">Đã Giao</th><th class="text-end">Thiếu</th></tr></thead><tbody>';
  var grouped=groupLines(o.lines||[]);
  grouped.forEach(function(l){
    var pname=l.product_id?l.product_id[1]:'Unknown';
    var wfree=(l.qty_warehouse_free||0)+(l.qty_reserved_here||0);
    var shortage=Math.max((l.product_uom_qty||0)-(l.qty_delivered||0)-(l.qty_packed||0)-wfree,0);
    var pending=(l.product_uom_qty||0)-(l.qty_delivered||0);
    var rc=pending>0?'table-warning':'table-success';
    var packCls=l.qty_packed>=l.product_uom_qty&&l.qty_packed>0?'cell-packed-full':(l.qty_packed>0?'cell-packed-partial':'cell-packed-zero');
    var stkCls=wfree>0?'cell-stock-ok':'cell-stock-zero';
    var packHtml=l.qty_packed>0?'<i class="fa fa-cube me-1"></i>'+fq(l.qty_packed)+(l.qty_packed>=l.product_uom_qty?' <i class="fa fa-check-circle"></i>':''):fq(0);
    h+='<tr class="'+rc+'"><td>'+esc(pname)+(l.is_kit?' <span class="badge bg-warning bg-opacity-25 text-dark" style="font-size:10px"><i class="fa fa-gift"></i> Combo</span>':'')+'</td>'
      +'<td class="text-end fw-bold">'+fq(l.product_uom_qty)+'</td>'
      +'<td class="text-end '+packCls+'">'+packHtml+'</td>'
      +'<td class="text-end '+stkCls+'">'+fq(wfree)+'</td>'
      +'<td class="text-end cell-delivered">'+fq(l.qty_delivered)+'</td>'
      +'<td class="text-end '+(shortage>0?'cell-shortage':'text-muted opacity-50')+'">'+fq(shortage)+'</td></tr>';
  });
  h+='</tbody></table>';
  if(o.pos&&o.pos.length){
    h+='<h6 class="mt-3"><i class="fa fa-truck"></i> Đơn mua hàng ('+o.pos.length+')</h6>'
      +'<ul class="list-group list-group-flush">';
    o.pos.forEach(function(p){
      var st=p.receipt_status||'pending';
      h+='<li class="list-group-item d-flex justify-content-between align-items-center py-2">'
        +'<span>'+esc(p.name)
        +(p.date_planned?' <small class="text-muted">('+fd(p.date_planned)+')</small>':'')
        +(p.partner_id?' <small class="text-muted">- '+esc(p.partner_id[1])+'</small>':'')
        +'</span>'
        +b(POC[st]||'badge-po-pending',POL[st]||st)
        +'</li>';
    });
    h+='</ul>';
  }
  $('dr-body').innerHTML=h;
  $('dr-footer').innerHTML='Trị giá: <span class="text-primary fs-5">'+fm(o.amount_total)+'</span>';
  $('drawer').classList.add('open');
  $('drawer-overlay').classList.add('open');
}

function closeDrawer(){
  $('drawer').classList.remove('open');
  $('drawer-overlay').classList.remove('open');
}

function updFilters(){
  var box=$('active-filters'),chips=[];
  if(gv('f-q')) chips.push({k:'f-q',v:'Tìm: '+gv('f-q'),reset:''});
  if(gv('f-wh')!=='all'){var s=$('f-wh');chips.push({k:'f-wh',v:'Kho: '+s.options[s.selectedIndex].text,reset:'all'});}
  if(gv('f-del')!=='all'){var s2=$('f-del');chips.push({k:'f-del',v:'Giao hàng: '+s2.options[s2.selectedIndex].text,reset:'all'});}
  if(gv('f-stk')!=='all'){var s3=$('f-stk');chips.push({k:'f-stk',v:'Kho: '+s3.options[s3.selectedIndex].text,reset:'all'});}
  if(gv('f-pack')!=='all'){var s4=$('f-pack');chips.push({k:'f-pack',v:'Đóng gói: '+s4.options[s4.selectedIndex].text,reset:'all'});}
  if(gv('f-date-from')) chips.push({k:'f-date-from',v:'Giao từ: '+gv('f-date-from'),reset:''});
  if(gv('f-date-to')) chips.push({k:'f-date-to',v:'Giao đến: '+gv('f-date-to'),reset:''});
  if(gv('f-po-date-from')) chips.push({k:'f-po-date-from',v:'Nhận từ: '+gv('f-po-date-from'),reset:''});
  if(gv('f-po-date-to')) chips.push({k:'f-po-date-to',v:'Nhận đến: '+gv('f-po-date-to'),reset:''});
  if(gv('f-po-status')!=='all'){var s5=$('f-po-status');chips.push({k:'f-po-status',v:'Mua hàng: '+s5.options[s5.selectedIndex].text,reset:'all'});}
  if(gv('f-saler')) chips.push({k:'f-saler',v:'NV MISA: '+gv('f-saler'),reset:''});
  if(gv('f-htgh')) chips.push({k:'f-htgh',v:'HTGH: '+gv('f-htgh'),reset:''});
  if(gv('f-dtype')!=='all'){var s6=$('f-dtype');chips.push({k:'f-dtype',v:'Vận chuyển: '+s6.options[s6.selectedIndex].text,reset:'all'});}
  // per-tag chips
  var tsel=$('f-tag');
  if(tsel){Array.from(tsel.selectedOptions).forEach(function(opt){
    chips.push({k:'f-tag-'+opt.value,v:'Tag: '+opt.text,tagId:opt.value});
  });}
  if(!chips.length){box.classList.add('d-none');return;}
  box.classList.remove('d-none');
  box.innerHTML='<i class="fa fa-filter text-muted small"></i> <small class="text-muted">Bộ lọc đang chọn:</small> '
    +chips.map(function(c){
      var attr=c.tagId!==undefined?'data-tag-id="'+c.tagId+'"':'data-fk="'+c.k+'" data-fr="'+(c.reset||'')+'"';
      return '<span class="badge bg-success filter-chip" '+attr+'>'
        +esc(c.v)+' <span class="chip-x" '+attr+'>&times;</span></span>';
    }).join('')
    +' <a href="#" id="clear-all-filters" class="small text-danger ms-1"><i class="fa fa-trash"></i> Xóa tất cả bộ lọc</a>';
}

document.addEventListener('click',function(e){
  var chipX=e.target.closest('.chip-x');
  if(chipX){
    e.preventDefault();e.stopPropagation();
    if(chipX.dataset.tagId){
      var tsel=$('f-tag');
      if(tsel){Array.from(tsel.options).forEach(function(o){if(o.value===chipX.dataset.tagId)o.selected=false;});}
    } else {
      var el=$(chipX.dataset.fk);
      if(el){el.value=chipX.dataset.fr||'';}
    }
    load(false);return;
  }
  var rBtn=e.target.closest('.btn-report');
  if(rBtn){e.stopPropagation();e.preventDefault();openReportModal(parseInt(rBtn.dataset.soId,10),rBtn.dataset.soName);return;}
  if(e.target.closest('#clear-all-filters')){e.preventDefault();clearAll();return;}
  var colMore=e.target.closest('.btn-col-more');
  if(colMore){
    e.preventDefault();
    var ck=colMore.getAttribute('data-col-key');
    S.kanbanColPageSize[ck]=(S.kanbanColPageSize[ck]||15)+15;
    renderKanban();return;
  }
  var card=e.target.closest('[data-so-id]');
  if(card){openDrawer(parseInt(card.dataset.soId,10));}
});

function clearAll(){
  ['f-q','f-date-from','f-date-to','f-po-date-from','f-po-date-to','f-saler','f-htgh'].forEach(function(id){var e=$(id);if(e)e.value='';});
  ['f-wh','f-stk','f-pack','f-po-status','f-dtype'].forEach(function(id){var e=$(id);if(e)e.value='all';});
  $('f-del').value='pending_partial';
  var ft=$('f-tag');if(ft){Array.from(ft.options).forEach(function(o){o.selected=false;});}
  S.kanbanColPageSize={};
  load(false);
}

$('btn-filter').addEventListener('click',function(){S.kanbanColPageSize={};load(false);});
$('f-q').addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();S.kanbanColPageSize={};load(false);}});
$('f-saler').addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();S.kanbanColPageSize={};load(false);}});
$('f-htgh').addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();S.kanbanColPageSize={};load(false);}});
$('btn-load-more').addEventListener('click',function(){load(true);});
$('btn-refresh').addEventListener('click',function(){S.kanbanColPageSize={};load(false);});

$('btn-kanban').addEventListener('click',function(){
  S.viewMode='kanban';
  this.className='btn btn-sm btn-primary';
  $('btn-list').className='btn btn-sm btn-outline-secondary';
  render();
});
$('btn-list').addEventListener('click',function(){
  S.viewMode='list';
  this.className='btn btn-sm btn-primary';
  $('btn-kanban').className='btn btn-sm btn-outline-secondary';
  render();
});

['grp-packing','grp-delivery','grp-stock'].forEach(function(id){
  $(id).addEventListener('click',function(){
    var map={'grp-packing':'packing_status','grp-delivery':'delivery_status','grp-stock':'stock_status'};
    S.kanbanGroupBy=map[id];
    S.kanbanColPageSize={};
    ['grp-packing','grp-delivery','grp-stock'].forEach(function(g){$(g).classList.remove('active');});
    this.classList.add('active');
    render();
  });
});

['kpi-pack-waiting','kpi-pack-unpacked','kpi-pack-done'].forEach(function(id){
  $(id).addEventListener('click',function(){
    var f=this.dataset.filter;
    var cur=gv('f-pack');
    $('f-pack').value=(cur===f)?'all':f;
    document.querySelectorAll('.kpi-pack').forEach(function(el){el.classList.remove('active');});
    if(cur!==f) this.classList.add('active');
    load(false);
  });
});

$('dr-close').addEventListener('click',closeDrawer);
$('drawer-overlay').addEventListener('click',closeDrawer);
document.addEventListener('keydown',function(e){if(e.key==='Escape'){closeDrawer();closeReportModal();}});

// --- Report modal ---
var _reportSoId=null;
function openReportModal(id,name){
  _reportSoId=id;
  $('report-so-name').textContent='Đơn hàng: '+name;
  $('report-reason').value='';
  var m=$('report-modal');m.style.display='flex';
  setTimeout(function(){$('report-reason').focus();},80);
}
function closeReportModal(){
  $('report-modal').style.display='none';
  _reportSoId=null;
}
$('report-cancel').addEventListener('click',closeReportModal);
$('report-modal').addEventListener('click',function(e){if(e.target===this)closeReportModal();});
$('report-submit').addEventListener('click',function(){
  if(!_reportSoId)return;
  var reason=$('report-reason').value.trim()||'(Không có mô tả)';
  var btn=this;btn.disabled=true;btn.innerHTML='<i class="fa fa-spinner fa-spin me-1"></i>Đang gửi...';
  fetch('/api/sale_plan/report_order',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({jsonrpc:'2.0',method:'call',params:{order_id:_reportSoId,reason:reason}})})
  .then(function(r){return r.json();})
  .then(function(j){
    btn.disabled=false;btn.innerHTML='<i class="fa fa-flag me-1"></i>Gửi báo cáo';
    if(j.result&&j.result.status==='success'){
      S.reportedIds[_reportSoId]=true;
      closeReportModal();
      render();
      var toast=document.createElement('div');
      toast.style.cssText='position:fixed;bottom:24px;right:24px;z-index:3000;background:#38a169;color:#fff;padding:12px 20px;border-radius:4px;box-shadow:0 4px 12px rgba(0,0,0,.2);font-weight:600';
      toast.innerHTML='<i class="fa fa-check me-1"></i>Đã gửi báo cáo cho admin';
      document.body.appendChild(toast);setTimeout(function(){toast.remove();},3500);
    } else {
      alert('Lỗi gửi báo cáo: '+(j.result&&j.result.message||'Lỗi không xác định'));
    }
  }).catch(function(){btn.disabled=false;btn.innerHTML='<i class="fa fa-flag me-1"></i>Gửi báo cáo';alert('Lỗi kết nối.');});
});

load(false);
})();
</script>
</body></html>"""


class SalePlanPublicController(http.Controller):

    @http.route('/sale_plan', type='http', auth='public', methods=['GET', 'POST'])
    def sale_plan_page(self, **kwargs):
        ip = request.httprequest.remote_addr
        conf_pw = (
            request.env['ir.config_parameter'].sudo()
            .get_param(PW_PARAM_KEY, default='') or ''
        )
        if not request.session.get(SESSION_KEY_OK):
            if request.httprequest.method == 'POST':
                if _is_rate_limited(ip):
                    return request.make_response(
                        _LOGIN.format(csrf=request.csrf_token(), err=_ERR_RATE),
                        headers=_H)
                inp = (request.params.get('inv_password') or '').strip()
                if inp == conf_pw:
                    request.session[SESSION_KEY_OK] = True
                    _FAIL_LOG.pop(ip, None)
                    return request.redirect('/sale_plan')
                _record_failure(ip)
                return request.make_response(
                    _LOGIN.format(csrf=request.csrf_token(), err=_ERR_PW),
                    headers=_H)
            return request.make_response(
                _LOGIN.format(csrf=request.csrf_token(), err=''),
                headers=_H)
        return request.make_response(_PAGE, headers=_H)

    @http.route('/api/sale_plan/data', type='json', auth='public', methods=['POST'])
    def api_sale_plan_data(self, search='', warehouse_id='all', delivery_status='all',
                           stock_status='all', packing_status='all',
                           date_from='', date_to='', po_date_from='', po_date_to='',
                           po_status='all', saler_code='', htgh='', delivery_type='all',
                           tag_ids='', limit=250, offset=0, **kwargs):
        if not request.session.get(SESSION_KEY_OK):
            return {'status': 'error', 'message': 'Unauthorized'}
        try:
            result = request.env['hlv.delivery.planner.service'].sudo().get_dashboard_data(
                search_query=search,
                filter_warehouse_id=warehouse_id,
                filter_delivery_status=delivery_status,
                filter_stock_status=stock_status,
                filter_packing_status=packing_status,
                filter_date_from=date_from,
                filter_date_to=date_to,
                filter_po_date_from=po_date_from,
                filter_po_date_to=po_date_to,
                filter_po_status=po_status,
                filter_saler_code=saler_code,
                filter_htgh=htgh,
                filter_delivery_type=delivery_type,
                filter_tag_ids=tag_ids,
                limit=int(limit),
                offset=int(offset),
            )
            return {'status': 'success', 'data': result}
        except Exception as e:
            _logger.exception('sale_plan API error')
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/sale_plan/report_order', type='json', auth='public', methods=['POST'])
    def api_report_order(self, order_id=None, reason='', **kwargs):
        if not request.session.get(SESSION_KEY_OK):
            return {'status': 'error', 'message': 'Unauthorized'}
        try:
            so = request.env['sale.order'].sudo().browse(int(order_id))
            if not so.exists():
                return {'status': 'error', 'message': 'Order not found'}
            safe_reason = Markup.escape(reason or '(Không có mô tả)')
            body = Markup(
                '<p>🚩 <strong>Báo cáo từ trang công khai (sale_plan):</strong></p>'
                '<blockquote>%s</blockquote>'
            ) % safe_reason
            so.message_post(body=body, message_type='comment', subtype_xmlid='mail.mt_note')
            so.x_plan_need_cancel = True
            return {'status': 'success'}
        except Exception as e:
            _logger.exception('report_order error')
            return {'status': 'error', 'message': str(e)}
