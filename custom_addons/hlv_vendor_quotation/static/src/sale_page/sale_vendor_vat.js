/* Ô tìm NCC (hộp lập phiếu + "Hỏi thêm NCC"): danh bạ không có NCC thì tạo nhanh bằng mã số thuế.
   - gõ MST mà không NCC nào trùng → dòng cuối "Tra MST … để tạo NCC";
   - bấm → khung dưới ô tìm: thông tin VietQR (tên, địa chỉ, tình trạng) hoặc liên hệ đã có MST đó;
   - "Tạo NCC" → controllers/sale_page_create.py (vat_create) tạo NCC, Odoo tự đẩy sang MISA
     (amis_callback) và ghi account_object_id; NCC mới vào phiếu luôn.
   Hai ô tìm dùng chung HQ.fetchVendors / HQ.vendorItemHtml / HQ.pickVendorItem. */
window.HlvQuote = window.HlvQuote || {};

(function (HQ) {
  "use strict";

  var esc = HQ.esc;

  /** NCC khớp chữ gõ + dòng tra MST (khi chữ gõ là MST chưa NCC nào có) hoặc dòng gợi ý gõ MST. */
  HQ.fetchVendors = function (term) {
    return HQ.rpc("/api/hoi-gia-ncc/partners", { search: term }).then(function (r) {
      var partners = r.partners || [];
      var vat = HQ.taxCode(term);
      if (vat) {
        var known = partners.some(function (p) { return HQ.taxCode(p.vat) === vat; });
        return known ? partners : partners.concat([{ vat_lookup: vat }]);
      }
      return partners.length ? partners : [{ vat_hint: true }];
    });
  };

  HQ.vendorItemHtml = function (p) {
    if (p.vat_lookup) {
      return '<span class="hq-crm-item">Không có trong danh bạ — tra MST ' + esc(p.vat_lookup) + " để tạo NCC</span>";
    }
    if (p.vat_hint) {
      return '<span class="hq-muted">Không tìm thấy. Chưa có NCC này? Gõ mã số thuế để tạo nhanh.</span>';
    }
    return esc(p.name) + (p.vat ? ' <span class="hq-muted">· MST ' + esc(p.vat) + "</span>" : "");
  };

  /**
   * Xử lý dòng được chọn trong ô tìm NCC. onVendor(partner {id, name, vat}) — việc của ô đó khi có NCC.
   * Trả chuỗi để ô tìm giữ chữ đang gõ (dòng gợi ý / đang tra MST), như HQ.bindPicker quy ước.
   */
  HQ.pickVendorItem = function (item, inputId, onVendor) {
    var input = HQ.$(inputId);
    if (item.vat_hint) {
      return input.value;
    }
    if (item.vat_lookup) {
      openBox(input, item.vat_lookup, onVendor);
      return input.value;
    }
    return onVendor(item);
  };

  /** Khung tra MST ngay dưới ô tìm (một khung cho mỗi ô; mở lại thì vẽ đè). */
  function openBox(input, vat, onVendor) {
    var picker = input.closest(".hq-picker") || input.parentNode;
    var box = picker.nextElementSibling;
    if (!box || !box.classList.contains("hq-vat-box")) {
      box = document.createElement("div");
      box.className = "hq-vat-box";
      picker.after(box);
      box.addEventListener("click", function (event) {
        var button = event.target.closest("button[data-vat-act]");
        if (button && !button.disabled) {
          act(box, button.dataset.vatAct);
        }
      });
    }
    box.vat = vat;
    box.onVendor = onVendor;
    box.innerHTML = '<div class="hq-loading">Đang tra MST ' + esc(vat) + "…</div>";
    HQ.rpc("/api/hoi-gia-ncc/vat_lookup", { vat: vat }).then(function (res) {
      box.lookup = res;
      render(box);
    }).catch(function (err) {
      box.innerHTML = head(vat) + '<div class="hq-vat-error">' + esc(err.message) + "</div>";
    });
  }

  function head(vat) {
    return '<div class="hq-share-head"><b>MST ' + esc(vat) + '</b><span class="hq-spacer"></span>' +
      '<button type="button" class="hq-btn hq-btn-mini" data-vat-act="close">Đóng</button></div>';
  }

  function render(box) {
    var res = box.lookup;
    var found = res.existing;
    var body;
    if (found && found.is_vendor) {
      body = "<div>Đã có NCC <b>" + esc(found.name) + "</b>.</div>" +
        '<button type="button" class="hq-btn hq-btn-primary hq-btn-mini" data-vat-act="use">Chọn NCC này</button>';
    } else if (found && found.active && found.root_company) {
      body = "<div>MST thuộc <b>" + esc(found.name) + "</b> — có trong danh bạ nhưng chưa là NCC.</div>" +
        '<button type="button" class="hq-btn hq-btn-primary hq-btn-mini" data-vat-act="create">Dùng làm NCC</button>';
    } else if (found) {
      body = '<div class="hq-vat-error">MST đang gắn trên "' + esc(found.name) + '"' +
        (found.active ? " (không phải công ty gốc)" : " (đã lưu trữ)") + ". Nhờ thu mua sửa liên hệ đó.</div>";
    } else {
      var b = res.business;
      body = "<div><b>" + esc(b.name) + "</b></div>" +
        (b.street ? '<div class="hq-muted">' + esc(b.street) + "</div>" : "") +
        (b.status ? '<div class="hq-muted">Tình trạng: ' + esc(b.status) + "</div>" : "") +
        '<button type="button" class="hq-btn hq-btn-primary hq-btn-mini" data-vat-act="create">Tạo NCC</button>';
    }
    box.innerHTML = head(res.vat) + '<div class="hq-vat-body">' + body + "</div>";
  }

  function act(box, action) {
    if (action === "close") {
      box.remove();
      return;
    }
    if (action === "use") {
      done(box, box.lookup.existing);
      return;
    }
    box.querySelectorAll("button[data-vat-act]").forEach(function (b) { b.disabled = true; });
    HQ.rpc("/api/hoi-gia-ncc/vat_create", { vat: box.vat }).then(function (res) {
      HQ.toast((res.created ? "Đã tạo NCC " : "Đã đánh dấu NCC ") + res.partner.name);
      done(box, res.partner);
    }).catch(function (err) {
      HQ.toast(err.message);
      render(box);
    });
  }

  function done(box, partner) {
    box.onVendor({ id: partner.id, name: partner.name, vat: partner.vat });
    var input = box.previousElementSibling && box.previousElementSibling.querySelector("input");
    if (input) {
      input.value = "";
    }
    box.remove();
  }
})(window.HlvQuote);
