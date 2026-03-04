# Tài liệu Kỹ thuật - Google Ads Automation

**Module:** `google_ads_automation`  
**Version:** 18.0.2.0.0

**Mục đích:** Tích hợp Odoo với Google Ads API để:
1. Quản lý tài khoản & đồng bộ chiến dịch
2. **Liên kết Sản phẩm Odoo ↔ Campaign Google Ads** (Product Feed)
3. **Tự động sinh Rules** dựa trên tồn kho, biên lợi nhuận, hiệu suất (Strategy)
4. Thực thi hành động lên Google Ads (Mutate API)

## 1. Cấu trúc thư mục

```text
google_ads_automation/
├── __init__.py
├── __manifest__.py
├── TECHNICAL.md
├── data/
│   └── ir_cron_data.xml
├── models/
│   ├── google_ads_account.py        # OAuth, sync API
│   ├── google_ads_campaign.py       # Campaign data + metrics
│   ├── google_ads_ad_group.py       # Ad Group data + metrics
│   ├── google_ads_ad.py             # Ad data + metrics
│   ├── google_ads_product_feed.py   # ★ Product Feed + Feed Lines (tồn kho, margin, avg sales)
│   ├── google_ads_strategy.py       # ★ Chiến lược tự động (5 loại) + sinh rules
│   ├── google_ads_rule.py           # ★ Rule Engine (product-aware + Google metrics)
│   └── google_ads_rule_log.py       # Log thực thi rules
├── services/
│   └── google_ads_mutate.py         # ★ Mutate API service (pause/enable campaign)
├── wizard/
│   └── google_ads_product_feed_wizard.py  # Wizard thêm SP vào Feed
├── security/
│   ├── ir.model.access.csv
│   └── google_ads_security.xml
└── views/
    ├── google_ads_account_views.xml
    ├── google_ads_campaign_views.xml
    ├── google_ads_ad_group_views.xml
    ├── google_ads_ad_views.xml
    ├── google_ads_product_feed_views.xml   # ★
    ├── google_ads_strategy_views.xml       # ★
    ├── google_ads_rule_views.xml
    └── menu_views.xml
```

## 2. Kiến trúc & Luồng xử lý

### 2.1. Product Feed (`google.ads.product.feed` + `.feed.line`)
- Liên kết `product.template` ↔ `google.ads.campaign` qua Many2many
- Computed fields từ Odoo: `qty_available`, `sale_price`, `cost_price`, `margin_percent`, `avg_daily_sales`, `days_of_stock`, `stock_status`
- `action_refresh_stock()` cập nhật lại toàn bộ dữ liệu
- Wizard `google.ads.product.feed.add.wizard` hỗ trợ thêm SP thủ công hoặc theo danh mục

### 2.2. Strategy (`google.ads.strategy`)
5 loại chiến lược:
| Type | Logic |
|---|---|
| `protect_low` | Tồn thấp → Pause campaign |
| `push_stock` | Tồn cao → Enable + tăng budget |
| `optimize_profit` | CPA cao hoặc Margin thấp → Pause |
| `push_new` | SP mới + đủ hàng → Enable |
| `auto_balance` | Kết hợp protect_low + push_stock + optimize_profit |

Các threshold cấu hình: `stock_low_threshold`, `stock_high_threshold`, `min_margin_percent`, `max_cpa`, `target_roas`, `budget_increase/decrease_percent`

Hàm chính: `action_generate_rules()` → sinh Rule records tự động

### 2.3. Rule Engine (`google.ads.rule`)
**Condition fields mở rộng**: `stock_qty`, `margin_percent`, `days_of_stock`, `avg_daily_sales`, `is_new_product` (ngoài các metrics Google cũ)

**Action types mở rộng**: `increase_budget`, `decrease_budget` (ngoài `pause`, `enable`, `notify`)

**Dry-run vs Live**: Khi `strategy.is_live = False` → chỉ ghi log + cập nhật DB nội bộ. Khi `True` → gọi Mutate API thực sự.

### 2.4. Mutate Service (`services/google_ads_mutate.py`)
- `GoogleAdsMutateService.pause_campaign(client, customer_id, campaign_id)`
- `GoogleAdsMutateService.enable_campaign(client, customer_id, campaign_id)`
- `update_campaign_budget()` — placeholder, cần test với tài khoản thật

### 2.5. Cron Flow
1. Sync metrics mới nhất từ Google (`action_sync_all_data`)
2. Cập nhật tồn kho cho tất cả Feed Lines (`action_refresh_stock`)
3. Chạy tất cả Rules active (`run_rule`)

## 3. Hướng dẫn mở rộng

- **Thêm Strategy mới**: Tạo method `_generate_rules_<type>()` trong `google_ads_strategy.py`, thêm selection value
- **Thêm Condition field**: Thêm selection value trong `google_ads_rule.py`, implement logic trong `_evaluate_condition_value()`
- **Thêm Action type**: Thêm selection value, implement trong `_execute_action()`
- **Budget Mutate API**: Implement `update_campaign_budget()` trong `services/google_ads_mutate.py`
