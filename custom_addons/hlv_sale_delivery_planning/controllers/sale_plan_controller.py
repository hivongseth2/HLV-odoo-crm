# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

SESSION_KEY_OK = "inv_pw_ok"
PW_PARAM_KEY = "website_public_inventory_18.search_password"
_H = [("Content-Type", "text/html; charset=utf-8")]

# ─── Login form ───────────────────────────────────────────────────────────────
_LOGIN = u"""<!DOCTYPE html>
<html lang="vi"><head>
<meta charset="utf-8"/>
<title>T\u00ecnh tr\u1ea1ng \u0111\u01a1n h\u00e0ng</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"/>
</head>
<body class="bg-light d-flex align-items-center justify-content-center" style="min-height:100vh">
<div class="card shadow p-4" style="max-width:400px;width:100%">
  <h4 class="fw-bold text-center text-primary mb-3">&#128666; T\u00ecnh tr\u1ea1ng \u0110\u01a1n h\u00e0ng</h4>
  {err}
  <form method="post" action="/sale_plan">
    <input type="hidden" name="csrf_token" value="{csrf}"/>
    <label class="form-label fw-bold">M\u1eadt kh\u1ea9u</label>
    <input type="password" name="inv_password" class="form-control form-control-lg mb-3" autofocus required/>
    <button type="submit" class="btn btn-primary w-100 btn-lg">X\u00e1c nh\u1eadn</button>
  </form>
</div>
</body></html>"""

_ERR = u'<div class="alert alert-danger mb-3">M\u1eadt kh\u1ea9u kh\u00f4ng \u0111\u00fang.</div>'

# ─── Main page ────────────────────────────────────────────────────────────────
_PAGE = u"""<!DOCTYPE html>
<html lang="vi"><head>
<meta charset="utf-8"/>
<title>T\u00ecnh tr\u1ea1ng \u0110\u01a1n h\u00e0ng</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/css/font-awesome.min.css"/>
<style>
body{{background:#f4f6f9;}}
.kpi-card{{border-radius:12px;padding:14px 18px;text-align:center;}}
.badge-del-pending{{background:#ffc107;color:#000;}}
.badge-del-partial{{background:#0dcaf0;color:#000;}}
.badge-del-full{{background:#198754;color:#fff;}}
.badge-stk-ready{{background:#198754;color:#fff;}}
.badge-stk-partial{{background:#ffc107;color:#000;}}
.badge-stk-out{{background:#dc3545;color:#fff;}}
.badge-pack-no{{background:#6c757d;color:#fff;}}
.badge-pack-partial{{background:#ffc107;color:#000;}}
.badge-pack-done{{background:#198754;color:#fff;}}
#tbl th,#tbl td{{vertical-align:middle;white-space:nowrap;}}
</style>
</head>
<body>
<nav class="navbar bg-white shadow-sm mb-3 px-3 navbar-expand-md">
  <a class="navbar-brand fw-bold text-primary" href="/sale_plan">
    <i class="fa fa-tasks me-1"></i> \u0110i\u1ec1u ph\u1ed1i Giao h\u00e0ng
  </a>
  <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#nm">
    <span class="navbar-toggler-icon"></span>
  </button>
  <div class="collapse navbar-collapse" id="nm">
    <div class="ms-auto d-flex gap-2 flex-wrap py-1">
      <a href="/search_stock" class="btn btn-sm btn-outline-primary"><i class="fa fa-cubes me-1"></i> T\u1ed3n kho</a>
      <a href="/search_order" class="btn btn-sm btn-outline-secondary"><i class="fa fa-file-text me-1"></i> Ch\u1ee9ng t\u1eeb mua</a>
      <a href="/sale_plan" class="btn btn-sm btn-success"><i class="fa fa-tasks me-1"></i> T\u00ecnh tr\u1ea1ng \u0111\u01a1n</a>
      <a href="/search_invoice" class="btn btn-sm btn-outline-info"><i class="fa fa-file-invoice me-1"></i> H\u00f3a \u0111\u01a1n MISA</a>
    </div>
  </div>
</nav>
<div class="container-fluid px-3 px-md-4">
  <!-- KPI -->
  <div class="row g-3 mb-3">
    <div class="col-6 col-md-3"><div class="kpi-card bg-white shadow-sm">
      <div class="text-muted small">T\u1ed5ng \u0111\u01a1n</div><div class="fs-4 fw-bold text-primary" id="kpi-total">\u2014</div>
    </div></div>
    <div class="col-6 col-md-3"><div class="kpi-card bg-white shadow-sm">
      <div class="text-muted small">Ch\u01b0a giao</div><div class="fs-4 fw-bold text-warning" id="kpi-pending">\u2014</div>
    </div></div>
    <div class="col-6 col-md-3"><div class="kpi-card bg-white shadow-sm">
      <div class="text-muted small">\u0110ang giao</div><div class="fs-4 fw-bold text-info" id="kpi-partial">\u2014</div>
    </div></div>
    <div class="col-6 col-md-3"><div class="kpi-card bg-white shadow-sm">
      <div class="text-muted small">Thi\u1ebfu h\u00e0ng</div><div class="fs-4 fw-bold text-danger" id="kpi-outstock">\u2014</div>
    </div></div>
  </div>
  <!-- Filters -->
  <div class="card shadow-sm border-0 mb-3 p-3">
    <div class="row g-2 align-items-end">
      <div class="col-md-4">
        <label class="form-label fw-bold small mb-1">T\u00ecm ki\u1ebfm</label>
        <input type="text" id="f-q" class="form-control" placeholder="T\u00ean \u0111\u01a1n, kh\u00e1ch h\u00e0ng..."/>
      </div>
      <div class="col-md-3">
        <label class="form-label fw-bold small mb-1">Kho</label>
        <select id="f-wh" class="form-select"><option value="all">T\u1ea5t c\u1ea3 kho</option></select>
      </div>
      <div class="col-md-3">
        <label class="form-label fw-bold small mb-1">T\u00ecnh tr\u1ea1ng giao</label>
        <select id="f-del" class="form-select">
          <option value="pending_partial">Ch\u01b0a + \u0110ang giao</option>
          <option value="all">T\u1ea5t c\u1ea3</option>
          <option value="pending">Ch\u01b0a giao</option>
          <option value="partial">\u0110ang giao</option>
          <option value="full">\u0110\u00e3 giao</option>
        </select>
      </div>
      <div class="col-md-2">
        <button id="btn-go" class="btn btn-primary w-100"><i class="fa fa-search me-1"></i> L\u1ecdc</button>
      </div>
    </div>
  </div>
  <!-- Table -->
  <div class="card shadow-sm border-0">
    <div class="table-responsive">
      <table class="table table-hover mb-0" id="tbl">
        <thead class="table-light"><tr>
          <th>\u0110\u01a1n h\u00e0ng</th>
          <th>Kh\u00e1ch h\u00e0ng</th>
          <th>Kho</th>
          <th>Ng\u00e0y \u0111\u1eb7t</th>
          <th>Giao d\u1ef1 ki\u1ebfn</th>
          <th class="text-end">T\u1ed5ng ti\u1ec1n</th>
          <th class="text-center">Giao h\u00e0ng</th>
          <th class="text-center">T\u1ed3n kho</th>
          <th class="text-center">\u0110\u00f3ng ki\u1ec7n</th>
        </tr></thead>
        <tbody id="tb"><tr><td colspan="9" class="text-center py-5">
          <div class="spinner-border text-primary"></div>
        </td></tr></tbody>
      </table>
    </div>
  </div>
  <!-- Pagination -->
  <div class="d-flex justify-content-between align-items-center mt-3 mb-5" id="pg-row" style="display:none!important">
    <span class="text-muted small" id="pg-info"></span>
    <nav><ul class="pagination mb-0">
      <li class="page-item" id="pg-p"><a class="page-link" href="#"><i class="fa fa-chevron-left"></i></a></li>
      <li class="page-item active"><span class="page-link" id="pg-lbl"></span></li>
      <li class="page-item" id="pg-n"><a class="page-link" href="#"><i class="fa fa-chevron-right"></i></a></li>
    </ul></nav>
  </div>
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
(function(){{
  var S = {{page:1,lim:20,total:0}};
  var DL={{'pending':'Ch\\u01b0a giao','partial':'\\u0110ang giao','full':'\\u0110\\u00e3 giao'}};
  var DC={{'pending':'badge-del-pending','partial':'badge-del-partial','full':'badge-del-full'}};
  var SL={{'ready':'\\u0110\\u1ee7 h\\u00e0ng','partial':'Thi\\u1ebfu h\\u00e0ng','out_of_stock':'H\\u1ebft h\\u00e0ng','no_stock_product':'N/A'}};
  var SC={{'ready':'badge-stk-ready','partial':'badge-stk-partial','out_of_stock':'badge-stk-out','no_stock_product':'badge-pack-no'}};
  var PL={{'not_packed':'Ch\\u01b0a \\u0111\\u00f3ng','partial':'\\u0110ang \\u0111\\u00f3ng','packed':'\\u0110\\u00e3 \\u0111\\u00f3ng','no_products':'N/A'}};
  var PC={{'not_packed':'badge-pack-no','partial':'badge-pack-partial','packed':'badge-pack-done','no_products':'badge-pack-no'}};
  function b(c,l){{return '<span class="badge '+(c||'bg-secondary')+'">'+(l||'\\u2014')+'</span>';}}
  function fd(s){{if(!s)return '\\u2014';var d=new Date(s.replace(' ','T'));return ('0'+d.getDate()).slice(-2)+'/'+ ('0'+(d.getMonth()+1)).slice(-2)+'/'+d.getFullYear();}}
  function fm(v){{return v?Math.round(v).toLocaleString('vi-VN')+'\\u20ab':'\\u2014';}}
  function wh(list){{
    var sel=document.getElementById('f-wh');
    if(sel.dataset.ok)return;sel.dataset.ok='1';
    list.forEach(function(w){{var o=document.createElement('option');o.value=w.id;o.text=w.name;sel.appendChild(o);}});
  }}
  function load(){{
    var tb=document.getElementById('tb');
    tb.innerHTML='<tr><td colspan="9" class="text-center py-5"><div class="spinner-border text-primary"></div></td></tr>';
    document.getElementById('pg-row').style.display='none';
    fetch('/api/sale_plan/data',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{jsonrpc:'2.0',method:'call',params:{{
        search:document.getElementById('f-q').value.trim(),
        warehouse_id:document.getElementById('f-wh').value||'all',
        delivery_status:document.getElementById('f-del').value||'all',
        stock_status:'all',packing_status:'all',
        limit:S.lim,offset:(S.page-1)*S.lim
      }}}})
    }})
    .then(function(r){{return r.json();}})
    .then(function(r){{
      var res=r.result||{{}};
      if(res.status!=='success'){{tb.innerHTML='<tr><td colspan="9" class="text-center text-danger py-4">L\\u1ed7i t\\u1ea3i d\\u1eef li\\u1ec7u.</td></tr>';return;}}
      var d=res.data;
      wh(d.warehouses||[]);
      var st=d.dashboard_stats||{{}};
      document.getElementById('kpi-total').textContent=d.total_count||0;
      document.getElementById('kpi-pending').textContent=st.pending||0;
      document.getElementById('kpi-partial').textContent=st.partial||0;
      document.getElementById('kpi-outstock').textContent=st.out_of_stock||0;
      S.total=d.total_count||0;
      var rows=d.orders||[];
      if(!rows.length){{
        tb.innerHTML='<tr><td colspan="9" class="text-center text-muted py-5"><i class="fa fa-inbox fa-2x d-block mb-2"></i>Kh\\u00f4ng c\\u00f3 \\u0111\\u01a1n h\\u00e0ng n\\u00e0o.</td></tr>';
        return;
      }}
      var h='';
      rows.forEach(function(o){{
        var ds=o.real_delivery_status||o.delivery_status||'';
        var ss=o.stock_status||'';var ps=o.packing_status||'';
        h+='<tr>';
        h+='<td class="fw-bold text-primary">'+(o.name||'')+'</td>';
        h+='<td>'+(o.partner_id?o.partner_id[1]:'\\u2014')+'</td>';
        h+='<td>'+(o.warehouse_id?o.warehouse_id[1]:'\\u2014')+'</td>';
        h+='<td>'+fd(o.date_order)+'</td>';
        h+='<td>'+fd(o.commitment_date)+'</td>';
        h+='<td class="text-end">'+fm(o.amount_total)+'</td>';
        h+='<td class="text-center">'+b(DC[ds],DL[ds]||ds)+'</td>';
        h+='<td class="text-center">'+b(SC[ss],SL[ss]||ss)+'</td>';
        h+='<td class="text-center">'+b(PC[ps],PL[ps]||ps)+'</td>';
        h+='</tr>';
      }});
      tb.innerHTML=h;
      pgRender();
    }})
    .catch(function(){{tb.innerHTML='<tr><td colspan="9" class="text-center text-danger py-4">Kh\\u00f4ng k\\u1ebft n\\u1ed1i \\u0111\\u01b0\\u1ee3c server.</td></tr>';}});
  }}
  function pgRender(){{
    var pages=Math.ceil(S.total/S.lim);
    var prow=document.getElementById('pg-row');
    if(pages<=1){{prow.style.display='none';return;}}
    prow.style.display='flex';
    document.getElementById('pg-info').textContent='Hi\\u1ec3n th\\u1ecb '+(Math.min((S.page-1)*S.lim+1,S.total))+' \\u2013 '+Math.min(S.page*S.lim,S.total)+' / '+S.total;
    document.getElementById('pg-lbl').textContent='Trang '+S.page+' / '+pages;
    document.getElementById('pg-p').classList.toggle('disabled',S.page<=1);
    document.getElementById('pg-n').classList.toggle('disabled',S.page>=pages);
  }}
  document.getElementById('btn-go').addEventListener('click',function(){{S.page=1;load();}});
  document.getElementById('f-q').addEventListener('keydown',function(e){{if(e.key==='Enter'){{S.page=1;load();}}}});
  document.getElementById('pg-p').addEventListener('click',function(e){{e.preventDefault();if(S.page>1){{S.page--;load();}}}});
  document.getElementById('pg-n').addEventListener('click',function(e){{e.preventDefault();var p=Math.ceil(S.total/S.lim);if(S.page<p){{S.page++;load();}}}});
  load();
}})();
</script>
</body></html>"""


class SalePlanPublicController(http.Controller):

    @http.route('/sale_plan', type='http', auth='public', methods=['GET', 'POST'])
    def sale_plan_page(self, **kwargs):
        conf_pw = (
            request.env['ir.config_parameter']
            .sudo()
            .get_param(PW_PARAM_KEY, default='') or ''
        )
        if not request.session.get(SESSION_KEY_OK):
            if request.httprequest.method == 'POST':
                inp = (request.params.get('inv_password') or '').strip()
                if inp == conf_pw:
                    request.session[SESSION_KEY_OK] = True
                    return request.redirect('/sale_plan')
                return request.make_response(
                    _LOGIN.format(csrf=request.csrf_token(), err=_ERR),
                    headers=_H,
                )
            return request.make_response(
                _LOGIN.format(csrf=request.csrf_token(), err=''),
                headers=_H,
            )
        return request.make_response(_PAGE, headers=_H)

    @http.route('/api/sale_plan/data', type='json', auth='public', methods=['POST'])
    def api_sale_plan_data(
        self, search='', warehouse_id='all', delivery_status='all',
        stock_status='all', packing_status='all',
        date_from='', date_to='', limit=20, offset=0, **kwargs
    ):
        if not request.session.get(SESSION_KEY_OK):
            return {'status': 'error', 'message': 'Unauthorized'}
        result = request.env['hlv.delivery.planner.service'].sudo().get_dashboard_data(
            search_query=search,
            filter_warehouse_id=warehouse_id,
            filter_delivery_status=delivery_status,
            filter_stock_status=stock_status,
            filter_packing_status=packing_status,
            filter_date_from=date_from,
            filter_date_to=date_to,
            filter_po_date_from='',
            filter_po_date_to='',
            filter_po_status='all',
            limit=int(limit),
            offset=int(offset),
        )
        return {'status': 'success', 'data': result}
