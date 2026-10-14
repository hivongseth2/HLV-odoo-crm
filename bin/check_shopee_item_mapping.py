# Khám phá dữ liệu trước khi cài hlv_shopee_product_check (kiểm map nhầm Shopee <-> Odoo). CHỈ ĐỌC.
#
# CÁCH CHẠY: sửa CẤU HÌNH bên dưới nếu cần, rồi copy TOÀN BỘ file này dán vào `odoo-bin shell`
# (Odoo.sh → Shell → odoo-bin shell, nên dùng production: staging bị neutralize khoá Shopee).
# Cả script nằm trong một lệnh exec(r'''...''') để dán vào shell tương tác không vỡ: dòng trống trong
# hàm không cắt khối lệnh, không có SystemExit làm thoát shell. Vẫn chạy được kiểu
# `odoo-bin shell -d <DB> < bin/check_shopee_item_mapping.py`.
#
# Shopee xoay refresh token: nếu token hết hạn, lời gọi API làm mới token và Shopee vô hiệu token cũ
# ngay. Shell không tự commit → DB còn token cũ đã chết → connector hỏng. Vì vậy script commit RIÊNG
# khi token của shop đổi (ngoài ra không ghi gì).
exec(r'''
# ── CẤU HÌNH ─────────────────────────────────────────────────────────────────
SAMPLE_PER_SHOP = 5     # số sản phẩm Shopee mỗi shop gọi thử API (0 = không gọi Shopee)
SAMPLE_ITEMS = []       # vd ["22650002151", "27116799261"] — gọi thử đúng các item id này
SHOP_FILTER = ""        # vd "DCCT TBCN" hoặc "4" — chỉ xét shop có tên chứa chuỗi này / đúng id
RAW = False             # True = in nguyên JSON Shopee trả về
LIST_MAX = 20           # mỗi danh sách in tối đa bấy nhiêu dòng
# ─────────────────────────────────────────────────────────────────────────────

import json
import logging
import time
from collections import Counter, defaultdict

from odoo.addons.sale_shopee import const, utils

# Như services/shopee_product_api.py của module (chưa deploy lên DB đang chạy script).
for _op, _path in (("get_item_base_info", "/api/v2/product/get_item_base_info"),
                   ("get_model_list", "/api/v2/product/get_model_list")):
    const.API_OPERATIONS_MAPPING.setdefault(_op, {"url_path": _path, "api_type": "product"})


def title(text):
    print("\n" + "=" * 100)
    print(text)
    print("=" * 100)


def model_key(value):
    text = str(value or "").strip()
    return "" if text in ("", "0") else text


def normalize(code):
    return "".join(str(code or "").split()).upper()


def short(text, size=300):
    text = " ".join(str(text or "").split())
    return text if len(text) <= size else text[:size] + "…"


def pct(part, whole):
    return "%s/%s (%.0f%%)" % (part, whole, 100.0 * part / whole) if whole else "0/0"


def describe(parts):
    return " + ".join("%g×[%s]" % (qty, part.default_code or part.name) for part, qty in parts.items()) or "-"


# ── 1. Môi trường ────────────────────────────────────────────────────────────
def section_environment():
    title("1. MÔI TRƯỜNG")
    names = ["sale_shopee", "combo_product", "mrp", "hlv_combo_to_bom", "hlv_product_agent", "hlv_shopee_product_check"]
    state = {m.name: m.state for m in env["ir.module.module"].sudo().search([("name", "in", names)])}
    for name in names:
        print("  %-26s %s" % (name, state.get(name, "KHÔNG CÓ TRONG DB")))
    try:
        import anthropic
        print("  thư viện anthropic        có (%s)" % getattr(anthropic, "__version__", "?"))
    except ImportError:
        print("  thư viện anthropic        [THIẾU] — bước AI sẽ báo lỗi")
    key = (env["ir.config_parameter"].sudo().get_param("hlv_product_agent.anthropic_api_key") or "").strip()
    print("  API key Claude            %s" % ("có (…%s)" % key[-4:] if key else "[THIẾU]"))


# ── 2. Shop ──────────────────────────────────────────────────────────────────
def section_shops():
    title("2. SHOP SHOPEE")
    shops = env["shopee.shop"].sudo().with_context(active_test=False).search([])
    if SHOP_FILTER:
        shops = shops.filtered(lambda s: SHOP_FILTER.lower() in (s.name or "").lower() or str(s.id) == SHOP_FILTER)
    for shop in shops:
        print("  id=%-4s %-35s shop_id=%-12s active=%s status=%s endpoint=%s" % (
            shop.id, shop.name, shop.shop_identifier, shop.active, shop.status, shop.account_id.api_endpoint))
        print("         token hết hạn: %s | uỷ quyền còn: %s ngày" % (
            shop.access_token_expiration_date, shop.authorization_remaining_days))
    if not shops:
        print("  Không có shop nào khớp SHOP_FILTER.")
    return shops


# ── 3. Liên kết shopee.item ──────────────────────────────────────────────────
def section_links(shops):
    title("3. LIÊN KẾT shopee.item")
    links = env["shopee.item"].sudo().search([("shop_id", "in", shops.ids)])
    placeholder = env.ref("sale_shopee.default_sale_product", raise_if_not_found=False)
    for shop in shops:
        shop_links = links.filtered(lambda link: link.shop_id == shop)
        kinds = Counter("0" if link.shopee_model_identifier == "0" else
                        ("rỗng" if not link.shopee_model_identifier else "id thật") for link in shop_links)
        print("\n  [%s id=%s] %s liên kết | model_identifier: %s | SP lưu trữ: %s | SP tạm: %s" % (
            shop.name, shop.id, len(shop_links), dict(kinds),
            len(shop_links.filtered(lambda link: not link.product_id.active)),
            len(shop_links.filtered(lambda link: placeholder and link.product_id == placeholder))))
        groups = defaultdict(list)
        for link in shop_links:
            groups[(link.shopee_item_identifier, model_key(link.shopee_model_identifier))].append(link)
        duplicates = [group for group in groups.values() if len(group) > 1]
        print("    Một phân loại gắn nhiều liên kết: %s" % len(duplicates))
        for group in duplicates[:LIST_MAX]:
            print("      item=%s → %s" % (group[0].shopee_item_identifier, " | ".join(
                "#%s [%s]" % (link.id, link.product_id.default_code) for link in group)))
    return links


# ── 4. Thành phần kit của sản phẩm Odoo được liên kết ───────────────────────
def section_kits(links):
    """Trả {product: thành phần kho xuất} — BoM kit trước, không có thì Combo Item (như module)."""
    title("4. SẢN PHẨM ODOO ĐƯỢC LIÊN KẾT — thành phần kit (BoM kit / Combo Item)")
    products = links.product_id.with_context(active_test=False)
    boms = env["mrp.bom"].sudo()._bom_find(products, bom_type="phantom")
    kits, stats, differ, bare_cb = {}, Counter(), [], []
    for product in products:
        bom = {line.product_id: line.product_qty for line in boms[product].bom_line_ids}
        combo = defaultdict(float)
        if product.product_tmpl_id.is_combo:
            for line in product.product_tmpl_id.combo_product_id:
                combo[line.product_id] += line.product_quantity
        kits[product] = bom or dict(combo)
        stats["bom"] += bool(bom)
        stats["combo"] += bool(combo)
        stats["both"] += bool(bom and combo)
        if bom and combo and {p.id: q for p, q in bom.items()} != {p.id: q for p, q in combo.items()}:
            differ.append((product, bom, combo))
        if not bom and not combo and (product.default_code or "").upper().startswith("CB"):
            bare_cb.append(product)
    total = len(products)
    print("  SP khác nhau được liên kết: %s" % total)
    print("  Có BoM kit: %s | có Combo Item: %s | có cả hai: %s" % (
        pct(stats["bom"], total), pct(stats["combo"], total), pct(stats["both"], total)))
    print("\n  BoM kit LỆCH Combo Item (module dùng BoM — kho xuất theo BoM): %s" % len(differ))
    for product, bom, combo in differ[:LIST_MAX]:
        print("    [%s] BoM: %s | Combo Item: %s" % (product.default_code, describe(bom), describe(dict(combo))))
    print("\n  Mã CB... không khai thành phần nào (AI chỉ còn đoán theo tên): %s" % len(bare_cb))
    for product in bare_cb[:LIST_MAX]:
        print("    [%s] %s" % (product.default_code, short(product.name, 90)))
    return kits


# ── 5. Shopee API thật ───────────────────────────────────────────────────────
def call(shop, operation, params):
    started = time.monotonic()
    result = utils.make_shopee_api_request(shop, operation, params=params)
    print("    · %s %.2fs" % (operation, time.monotonic() - started))
    if isinstance(result, dict) and isinstance(result.get("response"), dict):
        result = result["response"]
    return result if isinstance(result, dict) else {}


def shopee_variants(item, models_response):
    """{model_key: (tên phân loại, sku)} — cùng quy tắc với product_rules.shopee_units của module:
    phân loại không có SKU thì dùng SKU sản phẩm cha, không có model_name thì ghép từ tier_index."""
    if not item.get("has_model"):
        # Không phân loại: sale_shopee dò liên kết chỉ theo item_id — liên kết ghi id phân loại cũ vẫn dùng.
        return {None: ("", item.get("item_sku") or "")}
    tiers = (models_response or {}).get("tier_variation") or []
    result = {}
    for model in (models_response or {}).get("model") or []:
        name = model.get("model_name")
        if not name:
            options = []
            for level, index in enumerate(model.get("tier_index") or []):
                option_list = tiers[level].get("option_list") or [] if level < len(tiers) else []
                if index < len(option_list):
                    options.append(option_list[index].get("option") or "")
            name = " / ".join(options)
        result[model_key(model.get("model_id"))] = (name, model.get("model_sku") or item.get("item_sku") or "")
    return result


def pick_items(shop, links, kits):
    """Item id gọi thử: SAMPLE_ITEMS, không thì ưu tiên liên kết vào combo (chỗ hay map nhầm)."""
    shop_links = links.filtered(lambda link: link.shop_id == shop)
    if SAMPLE_ITEMS:
        wanted = set(shop_links.mapped("shopee_item_identifier"))
        return [str(i) for i in SAMPLE_ITEMS if str(i) in wanted]
    ordered = sorted(shop_links, key=lambda link: not (
        kits.get(link.product_id) or (link.product_id.default_code or "").upper().startswith("CB")))
    return list(dict.fromkeys(link.shopee_item_identifier for link in ordered))[:SAMPLE_PER_SHOP]


def sample_shop(shop, links, kits, totals):
    item_ids = pick_items(shop, links, kits)
    if not item_ids:
        return
    print("\n  [%s] gọi thử %s item: %s" % (shop.name, len(item_ids), ", ".join(item_ids)))
    data = call(shop, "get_item_base_info", {"item_id_list": ",".join(item_ids)})
    items = data.get("item_list") or []
    missing = set(item_ids) - {str(i.get("item_id")) for i in items}
    if missing:
        print("    [!] id không được trả (đã xoá?): %s" % sorted(missing))
    for item in items:
        totals["items"] += 1
        totals["item_keys"].update(item.keys())
        print("\n    ── item %s | %s" % (item.get("item_id"), short(item.get("item_name"), 120)))
        print("       status=%s has_model=%s item_sku=%r description_type=%r" % (
            item.get("item_status"), item.get("has_model"), item.get("item_sku"), item.get("description_type")))
        print("       description: %s" % short(item.get("description"), 200))
        if RAW:
            print(json.dumps(item, ensure_ascii=False, indent=1)[:4000])
        models_response = None
        if item.get("has_model"):
            models_response = call(shop, "get_model_list", {"item_id": int(item["item_id"])})
            for model in models_response.get("model") or []:
                totals["models"] += 1
                totals["model_keys"].update(model.keys())
            if RAW:
                print(json.dumps(models_response, ensure_ascii=False, indent=1)[:4000])
        # Cặp module sẽ gửi AI cho từng liên kết của item này.
        variants = shopee_variants(item, models_response)
        for link in links.filtered(lambda l: l.shop_id == shop and l.shopee_item_identifier == str(item.get("item_id"))):
            product = link.product_id
            variation, sku = variants.get(None) or variants.get(model_key(link.shopee_model_identifier), (None, None))
            print("       ▸ liên kết #%s model=%s" % (link.id, link.shopee_model_identifier))
            if variation is None:
                totals["stale", shop.id] += 1
                print("           [cũ] phân loại không còn trên Shopee → module xếp 'Liên kết cũ' (Odoo: [%s])"
                      % product.default_code)
                continue
            differ = normalize(sku) != normalize(product.default_code)
            totals["sku", shop.id, differ] += 1
            print("           Shopee: phân loại=%r sku=%r%s" % (variation, sku, "   ≠ SKU KHÁC MÃ ODOO" if differ else ""))
            print("           Odoo  : [%s] %s" % (product.default_code, short(product.name, 90)))
            print("           Odoo gồm (kit): %s" % describe(kits.get(product) or {}))


def section_api(shops, links, kits):
    title("5. SHOPEE API — mẫu thật (chỉ GET)")
    totals = Counter()
    totals["item_keys"], totals["model_keys"] = Counter(), Counter()
    for shop in shops:
        if shop.account_id.partner_key == "dummy" or shop.access_token == "dummy":
            # sale_shopee/data/neutralize.sql: Odoo.sh thay khoá Shopee bằng "dummy" khi tạo staging / bản sao.
            print("\n  [%s] DB đã neutralize (staging) — không gọi được Shopee. Chạy trên production." % shop.name)
            continue
        if not shop.active or not shop.access_token:
            print("\n  [%s id=%s] đã lưu trữ / chưa có token — bỏ qua." % (shop.name, shop.id))
            continue
        token_before = shop.access_token
        try:
            sample_shop(shop, links, kits, totals)
        except Exception as error:
            print("    [LỖI] %s: %s" % (type(error).__name__, short(error, 400)))
        finally:
            if shop.access_token != token_before:
                env.cr.commit()
                print("    [!] Token shop vừa được làm mới — đã commit token mới (bắt buộc, xem đầu file).")

    title("TÓM TẮT")
    print("  Liên kết trong mẫu: SKU phân loại khác mã Odoo (ứng viên map nhầm, AI sẽ soi) / trùng / liên kết cũ:")
    for shop in shops:
        counts = (totals["sku", shop.id, True], totals["sku", shop.id, False], totals["stale", shop.id])
        if any(counts):
            print("    %-35s %s khác / %s trùng / %s cũ" % (("%s id=%s" % (shop.name, shop.id),) + counts))
    print("\n  %s item — khoá Shopee trả về:" % totals["items"])
    for name, count in sorted(totals["item_keys"].items()):
        print("    %-28s %s" % (name, count))
    print("  %s model — khoá:" % totals["models"])
    for name, count in sorted(totals["model_keys"].items()):
        print("    %-28s %s" % (name, count))


def run():
    # sale_shopee ghi nguyên response Shopee ở mức INFO (vài chục KB mỗi lần gọi) — tắt trong lúc chạy.
    shopee_logger = logging.getLogger("odoo.addons.sale_shopee.utils")
    old_level = shopee_logger.level
    shopee_logger.setLevel(logging.WARNING)
    try:
        section_environment()
        shops = section_shops()
        if not shops:
            return
        links = section_links(shops)
        kits = section_kits(links)
        if SAMPLE_PER_SHOP or SAMPLE_ITEMS:
            section_api(shops, links, kits)
        else:
            print("\nSAMPLE_PER_SHOP = 0 → bỏ qua phần gọi Shopee.")
    finally:
        shopee_logger.setLevel(old_level)


run()
''', {"env": env, "__name__": "check_shopee_item_mapping"})  # noqa: F821 — env có sẵn trong odoo-bin shell
