# -*- coding: utf-8 -*-
import logging
import time
from collections import defaultdict
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
<div class="card shadow p-4" style="max-width:400px;width:100%">
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
<title>Điều phối Giao hàng</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/>
<style>
body{font-family:system-ui,-apple-system,sans-serif;background:#f0f2f5}
.kpi-card{border-radius:12px;transition:.2s;cursor:default}
.kpi-card:hover{transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,.12)}
.kpi-card.cursor-pointer{cursor:pointer}
.kpi-card h2{font-size:2rem}
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
.kanban-col{min-width:320px;max-width:400px;flex:1}
.kanban-col .card-header{font-size:.85rem}
#drawer{position:fixed;top:0;right:-700px;width:680px;height:100vh;background:#fff;
  box-shadow:-4px 0 24px rgba(0,0,0,.15);z-index:1060;transition:right .3s;overflow-y:auto}
#drawer.open{right:0}
#drawer-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.3);z-index:1055}
#drawer-overlay.open{display:block}
.filter-chip .btn-close{font-size:.6rem;margin-left:4px}
.table-lines td,.table-lines th{font-size:.85rem;vertical-align:middle}
.row-pending{background:#fff9e6}
.row-delivered{background:#e8f5e9}
.loading-overlay{position:fixed;inset:0;background:rgba(255,255,255,.6);z-index:2000;
  display:flex;align-items:center;justify-content:center}
.loading-overlay .spinner-border{width:3rem;height:3rem}
@media(max-width:768px){#drawer{width:100%} .kanban-col{min-width:100%}}
</style>
</head><body>
<div id="loading" class="loading-overlay d-none"><div class="spinner-border text-primary"></div></div>
<nav class="navbar navbar-expand-lg navbar-dark bg-primary mb-3">
<div class="container-fluid">
  <a class="navbar-brand fw-bold" href="/sale_plan">&#128666; Điều phối Giao hàng</a>
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
<!-- KPI -->
<div class="row g-2 mb-3">
  <div class="col-6 col-md-3"><div class="card kpi-card text-center p-3 border-primary border-2"><small class="text-muted">Đơn hàng</small><h2 class="text-primary mb-0" id="kpi-total">0</h2></div></div>
  <div class="col-6 col-md-3"><div class="card kpi-card text-center p-3 border-success border-2"><small class="text-muted">Sẵn sàng</small><h2 class="text-success mb-0" id="kpi-ready">0</h2></div></div>
  <div class="col-6 col-md-3"><div class="card kpi-card text-center p-3 border-warning border-2"><small class="text-muted">Có hàng 1 phần</small><h2 class="text-warning mb-0" id="kpi-partial">0</h2></div></div>
  <div class="col-6 col-md-3"><div class="card kpi-card text-center p-3 border-danger border-2"><small class="text-muted">Chưa có hàng/Thiếu</small><h2 class="text-danger mb-0" id="kpi-outstock">0</h2></div></div>
</div>
<!-- Packing KPIs -->
<div class="row g-2 mb-3">
  <div class="col-4"><div class="card kpi-card text-center p-3 cursor-pointer" id="kpi-pack-waiting" data-filter="waiting_stock"><small class="text-muted">Không có hàng đóng</small><h3 class="mb-0" id="kpi-pw">0</h3></div></div>
  <div class="col-4"><div class="card kpi-card text-center p-3 cursor-pointer" id="kpi-pack-unpacked" data-filter="unpacked"><small class="text-muted">Có hàng chưa đóng gói</small><h3 class="mb-0" id="kpi-pu">0</h3></div></div>
  <div class="col-4"><div class="card kpi-card text-center p-3 cursor-pointer" id="kpi-pack-done" data-filter="fully_packed"><small class="text-muted">Đã đóng gói đủ</small><h3 class="mb-0" id="kpi-pf">0</h3></div></div>
</div>
<!-- Active Filters -->
<div id="active-filters" class="mb-2 d-flex flex-wrap gap-1 align-items-center" style="display:none!important"></div>
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
  <div class="col-md-2"><label class="form-label small mb-0">Nhận hàng từ</label><input type="date" id="f-po-date-from" class="form-control form-control-sm"/></div>
  <div class="col-md-2"><label class="form-label small mb-0">Nhận hàng đến</label><input type="date" id="f-po-date-to" class="form-control form-control-sm"/></div>
  <div class="col-md-2"><label class="form-label small mb-0">Trạng Thái (Mua hàng)</label>
    <select id="f-po-status" class="form-select form-select-sm">
      <option value="all">Tất cả</option><option value="pending">Chưa nhận hàng</option>
      <option value="partial">Nhận 1 phần</option><option value="full">Đã nhận đủ</option>
    </select></div>
</div>
</div></div>
<!-- View toggle -->
<div class="d-flex justify-content-between align-items-center mb-2 flex-wrap gap-2">
  <div class="d-flex gap-1 flex-wrap">
    <button id="btn-kanban" class="btn btn-sm btn-primary"><i class="fa fa-th"></i> Kanban</button>
    <button id="btn-list" class="btn btn-sm btn-outline-secondary"><i class="fa fa-list"></i> Danh sách</button>
    <span class="vr mx-1"></span>
    <button id="grp-packing" class="btn btn-sm btn-outline-primary active">Đóng gói</button>
    <button id="grp-delivery" class="btn btn-sm btn-outline-primary">Tiến độ giao</button>
    <button id="grp-stock" class="btn btn-sm btn-outline-primary">Tình trạng kho</button>
  </div>
  <small class="text-muted" id="count-info">0 / 0 đơn hàng</small>
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
<!-- Pagination -->
<div id="pg-row" class="d-flex justify-content-between align-items-center my-3">
  <small id="pg-info" class="text-muted"></small>
  <div><button id="pg-prev" class="btn btn-sm btn-outline-secondary me-1">&#8592; Trước</button>
  <button id="pg-next" class="btn btn-sm btn-outline-secondary">Sau &#8594;</button></div>
</div>
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
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
(function(){
"use strict";
var S={page:1,limit:100,total:0,viewMode:'kanban',kanbanGroupBy:'packing_status',
  orders:[],warehouses:[],stats:{},whLoaded:false};

/* Translation maps */
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
function partnerName(o){return o.partner_id?o.partner_id[1]:'';}
function whName(o){return o.warehouse_id?o.warehouse_id[1]:'';}

function showLoading(){$('loading').classList.remove('d-none')}
function hideLoading(){$('loading').classList.add('d-none')}

function load(){
  showLoading();
  var body={search:gv('f-q'),warehouse_id:gv('f-wh'),delivery_status:gv('f-del'),
    stock_status:gv('f-stk'),packing_status:gv('f-pack'),
    date_from:gv('f-date-from'),date_to:gv('f-date-to'),
    po_date_from:gv('f-po-date-from'),po_date_to:gv('f-po-date-to'),
    po_status:gv('f-po-status'),limit:S.limit,offset:(S.page-1)*S.limit};
  fetch('/api/sale_plan/data',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({jsonrpc:'2.0',method:'call',params:body})})
  .then(function(r){return r.json()})
  .then(function(j){
    hideLoading();
    if(!j.result||j.result.status!=='success'){console.error('API error',j);return;}
    var d=j.result.data;
    S.orders=d.orders||[];
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
    updKPI();render();updPg();updFilters();
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
}

function render(){
  if(S.viewMode==='kanban') renderKanban(); else renderList();
  $('kanban-view').classList.toggle('d-none',S.viewMode!=='kanban');
  $('list-view').classList.toggle('d-none',S.viewMode!=='list');
  $('count-info').textContent=S.orders.length+' / '+S.total+' đơn hàng';
  /* Show/hide groupBy buttons only in kanban mode */
  ['grp-packing','grp-delivery','grp-stock'].forEach(function(id){
    $(id).style.display=S.viewMode==='kanban'?'':'none';
  });
}

function renderKanban(){
  var cols,gb=S.kanbanGroupBy;
  if(gb==='packing_status') cols=[
    {key:'waiting_stock',lbl:'Không có hàng đóng',cls:'text-secondary'},
    {key:'unpacked',lbl:'Có hàng chưa đóng gói',cls:'text-warning'},
    {key:'fully_packed',lbl:'Đã đóng gói đủ',cls:'text-success'}
  ];
  else if(gb==='delivery_status') cols=[
    {key:'unshipped',lbl:'Chưa giao',cls:'text-secondary'},
    {key:'partial',lbl:'Giao 1 phần',cls:'text-warning'},
    {key:'full',lbl:'Đã giao đủ',cls:'text-success'}
  ];
  else cols=[
    {key:'out_of_stock',lbl:'Không có hàng',cls:'text-danger'},
    {key:'partial_ready',lbl:'Có hàng 1 phần',cls:'text-warning'},
    {key:'ready',lbl:'Đủ hàng',cls:'text-success'}
  ];

  var wrap=$('kanban-view');wrap.innerHTML='';
  cols.forEach(function(c){
    /* For delivery groupBy, match on real_delivery_status; otherwise match field directly */
    var field=(gb==='delivery_status')?'real_delivery_status':gb;
    var items=S.orders.filter(function(o){return o[field]===c.key;});
    var col=document.createElement('div');col.className='kanban-col';
    col.innerHTML='<div class="card"><div class="card-header d-flex justify-content-between align-items-center '+c.cls+'">'
      +'<strong>'+c.lbl+'</strong><span class="badge bg-secondary rounded-pill">'+items.length+'</span></div>'
      +'<div class="card-body p-2 d-flex flex-column gap-2"></div></div>';
    wrap.appendChild(col);
    var body=col.querySelector('.card-body');
    items.forEach(function(o){
      var card=document.createElement('div');
      card.innerHTML=renderSOCard(o);
      body.appendChild(card.firstChild);
    });
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
  var h='<div class="card border-2 shadow-sm cursor-pointer '+bc+'" data-so-id="'+o.id+'">'
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
  h+='<div class="d-flex justify-content-between align-items-center">'
    +'<span class="fw-bold">'+fm(o.amount_total)+'</span>';
  var pc=o.pos?o.pos.length:0;
  if(pc>0) h+='<span class="badge bg-info text-dark">'+pc+' PO</span>';
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
    tr.innerHTML='<td class="fw-bold text-primary">'+esc(o.name)+'</td>'
      +'<td>'+esc(partnerName(o))+'</td>'
      +'<td>'+esc(whName(o))+'</td>'
      +'<td>'+fd(o.date_order)+'</td>'
      +'<td>'+fd(o.commitment_date)+'</td>'
      +'<td class="text-end">'+fm(o.amount_total)+'</td>'
      +'<td>'+b(DC[rd]||'',DL[rd]||'')+'</td>'
      +'<td>'+b(SC[o.stock_status]||'',SL[o.stock_status]||'')+'</td>'
      +'<td>'+b(PC[o.packing_status]||'',PL[o.packing_status]||'')+'</td>';
    tb.appendChild(tr);
  });
}

function updPg(){
  var pages=Math.ceil(S.total/S.limit)||1;
  $('pg-info').textContent='Trang '+S.page+' / '+pages+' ('+S.total+' đơn)';
  $('pg-prev').disabled=S.page<=1;
  $('pg-next').disabled=S.page>=pages;
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
    +'<strong><i class="fa fa-user"></i> '+esc(partnerName(o))+'</strong>'
    +' &mdash; <i class="fa fa-warehouse"></i> '+esc(whName(o))
    +'</div>';

  /* Product lines table */
  h+='<table class="table table-sm table-bordered table-lines"><thead class="table-light"><tr>'
    +'<th>Sản phẩm</th><th class="text-end">Chốt Bán</th><th class="text-end">Đóng Gói</th>'
    +'<th class="text-end">Tồn Kho</th><th class="text-end">Đã Giao</th><th class="text-end">Thiếu</th></tr></thead><tbody>';
  (o.lines||[]).forEach(function(l){
    var pname=l.product_id?l.product_id[1]:'Unknown';
    var shortage=Math.max((l.product_uom_qty||0)-(l.qty_delivered||0)-(l.qty_available||0),0);
    var rc=(l.qty_delivered>=l.product_uom_qty&&l.product_uom_qty>0)?'row-delivered':
           (l.qty_delivered>0?'row-pending':'');
    h+='<tr class="'+rc+'"><td>'+esc(pname)+'</td>'
      +'<td class="text-end">'+fq(l.product_uom_qty)+'</td>'
      +'<td class="text-end">'+fq(l.qty_packed||0)+'</td>'
      +'<td class="text-end">'+fq(l.qty_available||0)+'</td>'
      +'<td class="text-end">'+fq(l.qty_delivered)+'</td>'
      +'<td class="text-end '+(shortage>0?'text-danger fw-bold':'')+'">'+fq(shortage)+'</td></tr>';
  });
  h+='</tbody></table>';

  /* Purchase orders */
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
  var fv={search:gv('f-q'),warehouse_id:gv('f-wh'),delivery_status:gv('f-del'),
    stock_status:gv('f-stk'),packing_status:gv('f-pack'),
    date_from:gv('f-date-from'),date_to:gv('f-date-to'),
    po_date_from:gv('f-po-date-from'),po_date_to:gv('f-po-date-to'),
    po_status:gv('f-po-status')};
  if(fv.search) chips.push({k:'f-q',v:'Tìm: '+fv.search});
  if(fv.warehouse_id&&fv.warehouse_id!=='all'){var s=$('f-wh');chips.push({k:'f-wh',v:'Kho: '+s.options[s.selectedIndex].text});}
  if(fv.delivery_status&&fv.delivery_status!=='all'&&fv.delivery_status!=='pending_partial'){
    var s2=$('f-del');chips.push({k:'f-del',v:s2.options[s2.selectedIndex].text});}
  if(fv.stock_status&&fv.stock_status!=='all'){var s3=$('f-stk');chips.push({k:'f-stk',v:s3.options[s3.selectedIndex].text});}
  if(fv.packing_status&&fv.packing_status!=='all'){var s4=$('f-pack');chips.push({k:'f-pack',v:s4.options[s4.selectedIndex].text});}
  if(fv.date_from) chips.push({k:'f-date-from',v:'Giao từ: '+fv.date_from});
  if(fv.date_to) chips.push({k:'f-date-to',v:'Giao đến: '+fv.date_to});
  if(fv.po_date_from) chips.push({k:'f-po-date-from',v:'Nhận từ: '+fv.po_date_from});
  if(fv.po_date_to) chips.push({k:'f-po-date-to',v:'Nhận đến: '+fv.po_date_to});
  if(fv.po_status&&fv.po_status!=='all'){var s5=$('f-po-status');chips.push({k:'f-po-status',v:'PO: '+s5.options[s5.selectedIndex].text});}

  if(!chips.length){box.style.display='none';return;}
  box.removeAttribute('style');
  var html='';
  chips.forEach(function(c){
    html+='<span class="badge bg-primary filter-chip pe-1">'+esc(c.v)
      +' <button class="btn-close btn-close-white" data-fk="'+c.k+'"></button></span>';
  });
  html+=' <a href="#" id="clear-all-filters" class="small text-danger">Xóa tất cả bộ lọc</a>';
  box.innerHTML=html;
  box.querySelectorAll('.btn-close').forEach(function(bt){
    bt.addEventListener('click',function(){
      var el=$(bt.dataset.fk);if(!el)return;
      if(el.tagName==='SELECT'){
        el.value=(el.id==='f-del')?'pending_partial':'all';
      } else {el.value='';}
      S.page=1;load();
    });
  });
  var ca=$('clear-all-filters');
  if(ca) ca.addEventListener('click',function(e){e.preventDefault();clearAll();});
}

function clearAll(){
  ['f-q','f-date-from','f-date-to','f-po-date-from','f-po-date-to'].forEach(function(id){var e=$(id);if(e)e.value='';});
  ['f-wh','f-stk','f-pack','f-po-status'].forEach(function(id){var e=$(id);if(e)e.value='all';});
  $('f-del').value='pending_partial';
  S.page=1;load();
}

/* Delegate click for SO cards (kanban + list) */
document.addEventListener('click',function(e){
  var card=e.target.closest('[data-so-id]');
  if(card){openDrawer(parseInt(card.dataset.soId,10));}
});

/* Events */
$('btn-filter').addEventListener('click',function(){S.page=1;load();});
$('f-q').addEventListener('keydown',function(e){if(e.key==='Enter'){S.page=1;load();}});
$('pg-prev').addEventListener('click',function(){if(S.page>1){S.page--;load();}});
$('pg-next').addEventListener('click',function(){if(S.page*S.limit<S.total){S.page++;load();}});

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
    ['grp-packing','grp-delivery','grp-stock'].forEach(function(g){$(g).classList.remove('active');});
    this.classList.add('active');
    render();
  });
});

['kpi-pack-waiting','kpi-pack-unpacked','kpi-pack-done'].forEach(function(id){
  $(id).addEventListener('click',function(){
    var f=this.dataset.filter;
    var cur=gv('f-pack');
    /* Toggle: if already set to this value, reset to all */
    $('f-pack').value=(cur===f)?'all':f;
    S.page=1;load();
  });
});

$('dr-close').addEventListener('click',closeDrawer);
$('drawer-overlay').addEventListener('click',closeDrawer);
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeDrawer();});

/* Init */
load();
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
                           po_status='all', limit=100, offset=0, **kwargs):
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
                limit=int(limit),
                offset=int(offset),
            )
            return {'status': 'success', 'data': result}
        except Exception as e:
            _logger.exception('sale_plan API error')
            return {'status': 'error', 'message': str(e)}
