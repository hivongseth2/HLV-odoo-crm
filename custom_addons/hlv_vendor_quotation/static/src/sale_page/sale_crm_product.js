/* Lấy hàng từ MISA CRM vào hộp lập phiếu (controllers/sale_page_crm.py):
   - ô "Lấy hàng từ cơ hội MISA CRM": tìm cơ hội, chọn → mọi mặt hàng của cơ hội vào phiếu (đúng số
     lượng CRM), hàng Odoo chưa có thì tạo từ CRM; số cơ hội điền sẵn vào ô "Số cơ hội";
   - ô "Thêm sản phẩm" không thấy trong Odoo → dòng "Tìm trên MISA CRM" → khung kết quả CRM, bấm
     "Thêm" là tạo sản phẩm Odoo từ CRM rồi đưa vào phiếu;
   - khung dán danh sách (sale_paste.js) dùng HQ.crmMatchRows / HQ.crmImport cho dòng "không thấy". */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;
  var found = [];   // kết quả CRM đang hiện trong khung
  var OPP_MIN_SEARCH = 3;
  var opportunity = null;  // cơ hội vừa lấy hàng: {code, account, state, added, created, failed}

  /* ---------------- Lấy hàng từ cơ hội CRM ---------------- */

  HQ.resetOpportunityPick = function () {
    opportunity = null;
    renderOpportunity();
  };

  function renderOpportunity() {
    var box = HQ.$("hq-opp-chip");
    if (!opportunity) {
      box.innerHTML = "";
      return;
    }
    var o = opportunity;
    var head = "Cơ hội " + esc(o.code) + (o.account ? " · " + esc(o.account) : "");
    if (o.state === "loading") {
      box.innerHTML = '<span class="hq-muted">Đang lấy hàng của ' + head + " từ MISA CRM…</span>";
      return;
    }
    box.innerHTML = '<span class="hq-chip hq-chip-blue">' + head +
      '<button type="button" class="hq-chip-x" data-opp-clear="1" title="Ẩn">×</button></span>' +
      '<span class="hq-muted">Đã thêm ' + o.added + " mặt hàng" +
      (o.created ? " (" + o.created + " tạo mới từ CRM)" : "") + "; số cơ hội điền sẵn ở bước 3.</span>" +
      (o.failed.length ? '<div class="hq-alert hq-alert-strong">Không thêm được: ' + o.failed.map(esc).join("; ") +
        ". Tìm tay ở ô \"Thêm sản phẩm\".</div>" : "");
  }

  /** Chọn một cơ hội: lấy hàng, tạo hàng Odoo còn thiếu (trừ combo), thêm cả vào phiếu. */
  function pickOpportunity(item) {
    opportunity = { code: item.code, account: item.account, state: "loading", added: 0, created: 0, failed: [] };
    renderOpportunity();
    HQ.rpc("/api/hoi-gia-ncc/crm_opportunity_lines", { opportunity_id: item.id }).then(function (res) {
      var rows = res.lines || [];
      var missing = rows.filter(function (row) { return !row.product && !row.is_combo; });
      var combos = rows.filter(function (row) { return !row.product && row.is_combo; });
      return (missing.length ? HQ.crmImport(missing.map(function (row) { return row.code; })) : Promise.resolve([]))
        .then(function (results) {
          var lines = rows.filter(function (row) { return row.product; }).map(function (row) { return row.product; });
          var failed = combos.map(function (row) { return row.code + " (combo — tạo qua đơn bán)"; });
          missing.forEach(function (row, i) {
            var result = results[i] || {};
            if (result.product) {
              lines.push(Object.assign({}, result.product, { qty: row.qty || 1 }));
            } else {
              failed.push(row.code + (result.error ? " (" + result.error + ")" : ""));
            }
          });
          HQ.addCreateLines(lines);
          HQ.$("hq-opportunity").value = item.code;
          Object.assign(opportunity, {
            state: "done", added: lines.length, failed: failed,
            created: results.filter(function (r) { return r.created; }).length,
          });
          if (!rows.length) {
            opportunity.failed = ["cơ hội này chưa có mặt hàng nào trên CRM"];
          }
          renderOpportunity();
        });
    }).catch(function (err) {
      opportunity = null;
      renderOpportunity();
      HQ.toast(err.message);
    });
  }

  /** Dòng đã dán → [{best: mã CRM chắc chắn hoặc "", candidates}] cùng thứ tự. */
  HQ.crmMatchRows = function (lines) {
    return HQ.rpc("/api/hoi-gia-ncc/crm_match_rows", { lines: lines }).then(function (res) { return res.rows || []; });
  };

  /** Mã CRM → [{code, product?, created?, error?}] cùng thứ tự (server tạo sản phẩm nếu Odoo chưa có). */
  HQ.crmImport = function (codes) {
    return HQ.rpc("/api/hoi-gia-ncc/import_products", { codes: codes }).then(function (res) { return res.results || []; });
  };

  /** "mã — tên · ĐVT" của một hàng CRM (ô chọn, danh sách). */
  HQ.crmLabel = function (p) {
    return p.code + " — " + p.name + (p.unit ? " · " + p.unit : "");
  };

  HQ.openCrmSearch = function (term) {
    var box = HQ.$("hq-crm-results");
    HQ.show("hq-crm-results", true);
    box.innerHTML = '<div class="hq-loading">Đang tìm "' + esc(term) + '" trên MISA CRM…</div>';
    HQ.rpc("/api/hoi-gia-ncc/crm_products", { search: term }).then(function (res) {
      found = res.products || [];
      render(term);
    }).catch(function (err) {
      box.innerHTML = '<div class="hq-alert">' + esc(err.message) + "</div>";
    });
  };

  function render(term) {
    var head = '<div class="hq-share-head"><b>Trên MISA CRM</b><span class="hq-muted">"' + esc(term) +
      '" — chưa có trong Odoo thì bấm Thêm để tạo sản phẩm (tên, ĐVT, giá, thuế theo CRM).</span>' +
      '<span class="hq-spacer"></span><button type="button" class="hq-btn hq-btn-mini" data-crm-close="1">Đóng</button></div>';
    if (!found.length) {
      HQ.$("hq-crm-results").innerHTML = head + '<div class="hq-muted">MISA CRM cũng không có hàng này.</div>';
      return;
    }
    HQ.$("hq-crm-results").innerHTML = head + '<div class="hq-table-wrap"><table class="hq-table"><tbody>' +
      found.map(function (p, index) {
        return "<tr><td class=\"hq-nowrap\">" + esc(p.code) + "</td><td>" + esc(p.name) +
          (p.odoo_exists ? ' <span class="hq-tag hq-tag-ok">Odoo đã có</span>' : "") + "</td>" +
          "<td>" + esc(p.unit) + '</td><td class="hq-num">' + (p.price ? HQ.money(p.price) : "") + "</td>" +
          '<td class="hq-num">' + (p.is_combo
            ? '<span class="hq-muted" title="Hàng combo cần dựng thành phần — tạo qua đơn bán">combo</span>'
            : '<button type="button" class="hq-btn hq-btn-mini hq-btn-primary" data-crm-add="' + index + '">Thêm</button>') +
          "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }

  function add(button, item) {
    button.disabled = true;
    HQ.crmImport([item.code]).then(function (results) {
      var result = results[0] || {};
      if (result.error) {
        throw new Error(result.error);
      }
      HQ.addCreateLines([result.product]);
      HQ.toast(result.created ? "Đã tạo sản phẩm " + item.code + " từ MISA CRM và thêm vào phiếu"
        : "Đã thêm " + item.code + " vào phiếu");
      HQ.show("hq-crm-results", false);
    }).catch(function (err) {
      button.disabled = false;
      HQ.toast(err.message);
    });
  }

  HQ.bindCrmEvents = function () {
    var modal = HQ.$("hq-modal");
    // Mỗi lần tìm là một lần gọi CRM — đợi gõ đủ vài ký tự.
    HQ.bindPicker("hq-opp-search", "hq-opp-results", function (term) {
      if (term.length < OPP_MIN_SEARCH) {
        return Promise.resolve([]);
      }
      return HQ.rpc("/api/hoi-gia-ncc/crm_opportunities", { search: term }).then(function (r) { return r.opportunities; });
    }, function (o) {
      return '<span class="hq-strong">' + esc(o.code) + "</span> " + esc(o.account || o.name) +
        '<div class="hq-muted hq-small">' + esc([o.stage, o.owner, o.products].filter(Boolean).join(" · ")) + "</div>";
    }, pickOpportunity);
    HQ.on(modal, "click", "[data-opp-clear]", HQ.resetOpportunityPick);
    HQ.on(modal, "click", "[data-crm-add]", function (el) { add(el, found[+el.dataset.crmAdd]); });
    HQ.on(modal, "click", "[data-crm-close]", function () { HQ.show("hq-crm-results", false); });
  };
})(window.HlvQuote);
