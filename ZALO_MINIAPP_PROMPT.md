# Prompt: Xây dựng Zalo Mini App — HLV Loyalty

> Sử dụng tài liệu này làm thông số kỹ thuật đầy đủ để xây dựng Zalo Mini App kết nối với hệ thống Loyalty của Odoo HLV.

---

## 1. Tổng quan

Xây dựng một Zalo Mini App cho phép khách hàng:
- Tra cứu điểm thưởng, hạng thành viên
- Xem lịch sử giao dịch điểm
- Xem & sử dụng Voucher
- Đổi điểm lấy quà / tiền mặt
- Xem quyền lợi theo hạng thành viên

**Backend**: Odoo 18 tại `https://<domain>` (thay bằng domain thực)
**Auth**: Không cần đăng nhập riêng — dùng Zalo `getUserInfo()` lấy số điện thoại → tra cứu partner trên Odoo.

---

## 2. Tech Stack

| Thành phần | Lựa chọn |
|---|---|
| Platform | Zalo Mini App (ZMP SDK) |
| UI Framework | React + TypeScript |
| UI Library | ZMP UI (`zmp-ui`) |
| HTTP Client | `axios` hoặc native `fetch` |
| State | React Context hoặc Zustand |
| Router | ZMP Router (`zmp-router`) |
| Storage | `localStorage` (via ZMP API) |

### Khởi tạo project

```bash
npm create zmp-app@latest hlv-loyalty-miniapp
# Chọn: React + TypeScript template
cd hlv-loyalty-miniapp
npm install axios
```

---

## 3. Cấu trúc thư mục

```
src/
  api/          # Tất cả hàm gọi API
    loyalty.ts
    types.ts
  components/   # UI tái sử dụng
    PointBadge.tsx
    TierCard.tsx
    VoucherCard.tsx
    HistoryItem.tsx
    RedeemForm.tsx
  pages/        # Màn hình chính
    HomePage.tsx
    HistoryPage.tsx
    VouchersPage.tsx
    RedeemPage.tsx
    ProfilePage.tsx
  hooks/
    usePartner.ts
    useTiers.ts
  store/
    AppContext.tsx
  utils/
    format.ts
  App.tsx
  app-config.json
```

---

## 4. Base URL & Constants

```typescript
// src/api/loyalty.ts
const BASE_URL = 'https://<your-odoo-domain>';

// Tất cả endpoint ngoại trừ /api/loyalty/* đều auth='public'
// Không cần Authorization header
```

---

## 5. Data Types (TypeScript)

```typescript
// src/api/types.ts

export interface Tier {
  id: number;
  name: string;
  min_points: number;
  max_points: number | null;
  color: string;
  badge_color: string;
  image_url: string;
  icon: string;
  description: string;
  benefits: string[];
}

export interface PartnerSummary {
  id: number;
  name: string;
  phone: string;
  email: string;
  total_points: number;
  image_url: string;
  tier: Tier | null;
  tier_image_url: string;
  next_tier: Tier | null;
  next_tier_image_url: string;
  points_to_next: number;
  // chi tiết (từ GET /partner/<id>)
  active_vouchers?: Voucher[];
  recent_history?: HistoryRecord[];
}

export interface HistoryRecord {
  id: number;
  date: string;          // ISO datetime
  point_amount: number;  // dương = cộng, âm = trừ
  transaction_type: 'earn' | 'exchange' | 'manual' | 'return' | string;
  description: string;
}

export interface HistoryResponse {
  partner_id: number;
  total_points: number;
  total_records: number;
  limit: number;
  offset: number;
  records: HistoryRecord[];
}

export interface Voucher {
  id: number;
  code: string;
  state: 'active' | 'used' | 'expired' | 'cancelled';
  discount_type: 'percent' | 'fixed';
  discount_value: number;
  max_discount_amount: number;
  date_issued: string | null;
  date_expiry: string | null;
  package_name: string;
}

export interface VoucherValidation {
  valid: boolean;
  error?: string;
  voucher?: {
    id: number;
    code: string;
    discount_type: string;
    discount_value: number;
    estimated_discount: number;
    date_expiry: string | null;
    partner_id: number;
    partner_name: string;
  };
}
```

---

## 6. API Functions

```typescript
// src/api/loyalty.ts
import axios from 'axios';
import type { PartnerSummary, HistoryResponse, Voucher, Tier, VoucherValidation } from './types';

const BASE_URL = 'https://<your-odoo-domain>';
const api = axios.create({ baseURL: BASE_URL });

// ── 6.1 Tìm khách hàng theo SĐT ─────────────────────────────────────────
// GET /api/v1/loyalty/partner/lookup?phone=0901234567
// Tìm qua portal_phone (đã chuẩn hóa) + phone + mobile (không cần customer_rank)
export async function lookupPartnerByPhone(phone: string): Promise<PartnerSummary | null> {
  const { data } = await api.get('/api/v1/loyalty/partner/lookup', { params: { phone } });
  return Array.isArray(data) ? data[0] : data;
}

// ── 6.2 Lấy thông tin đầy đủ partner (điểm + hạng + voucher + lịch sử gần nhất) ──
// GET /api/v1/loyalty/partner/<id>
export async function getPartner(partnerId: number): Promise<PartnerSummary> {
  const { data } = await api.get(`/api/v1/loyalty/partner/${partnerId}`);
  return data;
}

// ── 6.3 Lịch sử giao dịch (phân trang) ─────────────────────────────────
// GET /api/v1/loyalty/partner/<id>/history?limit=20&offset=0
export async function getHistory(partnerId: number, limit = 20, offset = 0): Promise<HistoryResponse> {
  const { data } = await api.get(`/api/v1/loyalty/partner/${partnerId}/history`, {
    params: { limit, offset },
  });
  return data;
}

// ── 6.4 Danh sách Voucher ────────────────────────────────────────────────
// GET /api/v1/loyalty/vouchers/<id>?state=active
export async function getVouchers(partnerId: number, state?: string): Promise<Voucher[]> {
  const { data } = await api.get(`/api/v1/loyalty/vouchers/${partnerId}`, {
    params: state ? { state } : {},
  });
  return data;
}

// ── 6.5 Validate Voucher ─────────────────────────────────────────────────
// POST /api/v1/loyalty/voucher/validate  (JSON-RPC)
// Body: { "code": "VHQ-XXXXX", "partner_id": 42, "order_amount": 500000 }
export async function validateVoucher(
  code: string, partnerId: number, orderAmount = 0
): Promise<VoucherValidation> {
  const { data } = await api.post('/api/v1/loyalty/voucher/validate', {
    jsonrpc: '2.0', method: 'call', id: 1,
    params: { code, partner_id: partnerId, order_amount: orderAmount },
  });
  return data.result;
}

// ── 6.6 Danh sách hạng thành viên ───────────────────────────────────────
// GET /api/v1/loyalty/tiers
export async function getTiers(): Promise<Tier[]> {
  const { data } = await api.get('/api/v1/loyalty/tiers');
  return data;
}

// ── 6.7 Ảnh đại diện partner ────────────────────────────────────────────
// GET /api/v1/loyalty/partners/<id>/image  → binary image
export function getPartnerImageUrl(partnerId: number): string {
  return `${BASE_URL}/api/v1/loyalty/partners/${partnerId}/image`;
}

// ── 6.8 Ảnh hạng thành viên ─────────────────────────────────────────────
// GET /api/v1/loyalty/tiers/<id>/image  → binary image
export function getTierImageUrl(tierId: number): string {
  return `${BASE_URL}/api/v1/loyalty/tiers/${tierId}/image`;
}
```

---

## 7. Luồng đăng nhập (Auth Flow)

```
[Mở App]
    ↓
Kiểm tra localStorage có partner_id không?
    ├─ Có → load getPartner(partner_id) → Home
    └─ Không →
         ↓
    ZMP.getUserInfo() → lấy số điện thoại (cần user cấp quyền)
         ↓
    lookupPartnerByPhone(phone)
         ├─ Tìm thấy → lưu partner_id vào localStorage → Home
         └─ Không tìm thấy → Màn hình "Số điện thoại chưa đăng ký"
              (hiện số hotline / link đăng ký)
```

```typescript
// src/hooks/usePartner.ts
import { useState, useEffect } from 'react';
import { getUserInfo } from 'zmp-sdk/apis';
import { lookupPartnerByPhone, getPartner } from '../api/loyalty';
import type { PartnerSummary } from '../api/types';

export function usePartner() {
  const [partner, setPartner] = useState<PartnerSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    async function init() {
      try {
        // 1. Kiểm tra cache
        const cached = localStorage.getItem('loyalty_partner_id');
        if (cached) {
          const data = await getPartner(Number(cached));
          setPartner(data);
          return;
        }
        // 2. Lấy thông tin Zalo
        const { userInfo } = await getUserInfo({ autoRequestPermission: true });
        const phone = userInfo.phone; // cần user cấp quyền số điện thoại
        if (!phone) { setNotFound(true); return; }
        // 3. Tra cứu partner
        const found = await lookupPartnerByPhone(phone);
        if (!found) { setNotFound(true); return; }
        localStorage.setItem('loyalty_partner_id', String(found.id));
        setPartner(found);
      } finally {
        setLoading(false);
      }
    }
    init();
  }, []);

  return { partner, loading, notFound, setPartner };
}
```

---

## 8. Màn hình & Components

### 8.1 HomePage — Trang chủ / Dashboard

**Dữ liệu**: `getPartner(partner_id)`

**Hiển thị**:
- Avatar + tên khách hàng
- Thẻ hạng thành viên: tên hạng, màu, icon, thanh tiến độ lên hạng tiếp theo
- Tổng điểm (số lớn, nổi bật)
- "Điểm để lên hạng [tên hạng tiếp theo]": `points_to_next`
- Danh sách 3–5 giao dịch gần nhất (`recent_history`)
- Nút "Xem tất cả lịch sử" → HistoryPage
- Nút "Đổi điểm" → RedeemPage
- Nút "Voucher của tôi" → VouchersPage

```tsx
// src/pages/HomePage.tsx
import { Page, Box, Text, Avatar, ProgressBar, Button } from 'zmp-ui';
import { usePartner } from '../hooks/usePartner';
import TierCard from '../components/TierCard';
import HistoryItem from '../components/HistoryItem';

export default function HomePage() {
  const { partner, loading } = usePartner();
  if (loading) return <Page><Box className="flex-center"><Spinner /></Box></Page>;

  return (
    <Page className="home-page">
      {/* Header: avatar + tên */}
      <Box className="profile-header">
        <Avatar src={partner?.image_url} size={56} />
        <Text.Title>{partner?.name}</Text.Title>
        <Text size="small" className="phone">{partner?.phone}</Text>
      </Box>

      {/* Thẻ điểm */}
      <Box className="points-card" style={{ background: partner?.tier?.color ?? '#e63946' }}>
        <Text size="xSmall" className="label">ĐIỂM TÍCH LŨY</Text>
        <Text.Title size="large" bold>{partner?.total_points?.toLocaleString()}</Text.Title>
        <Text size="xSmall">{partner?.tier?.name ?? 'Chưa có hạng'}</Text>
      </Box>

      {/* Tiến độ hạng */}
      {partner?.next_tier && (
        <Box className="tier-progress">
          <Text size="xSmall">Thêm {partner.points_to_next.toLocaleString()} điểm để lên {partner.next_tier.name}</Text>
          <ProgressBar
            percent={Math.min(
              100,
              ((partner.total_points - (partner.tier?.min_points ?? 0)) /
               (partner.next_tier.min_points - (partner.tier?.min_points ?? 0))) * 100
            )}
          />
        </Box>
      )}

      {/* Action buttons */}
      <Box className="action-row">
        <Button onClick={() => navigate('/redeem')}>Đổi điểm</Button>
        <Button variant="secondary" onClick={() => navigate('/vouchers')}>Voucher</Button>
        <Button variant="secondary" onClick={() => navigate('/history')}>Lịch sử</Button>
      </Box>

      {/* Lịch sử gần nhất */}
      <Box className="recent-history">
        <Text.Title size="small">Giao dịch gần nhất</Text.Title>
        {partner?.recent_history?.slice(0, 5).map(h => (
          <HistoryItem key={h.id} record={h} />
        ))}
        <Button variant="text" onClick={() => navigate('/history')}>Xem tất cả →</Button>
      </Box>
    </Page>
  );
}
```

---

### 8.2 HistoryPage — Lịch sử điểm

**Dữ liệu**: `getHistory(partner_id, limit, offset)` — phân trang vô hạn (infinite scroll)

**Hiển thị**:
- Tổng số điểm (header sticky)
- Danh sách giao dịch: ngày, loại (cộng/trừ), số điểm, mô tả
- Infinite scroll: load thêm khi cuộn xuống cuối
- Màu xanh = cộng điểm, màu đỏ = trừ điểm

```tsx
// src/components/HistoryItem.tsx
export default function HistoryItem({ record }: { record: HistoryRecord }) {
  const isEarn = record.point_amount > 0;
  return (
    <Box className="history-item">
      <Box className="left">
        <Text size="small" bold>{record.description || transactionLabel(record.transaction_type)}</Text>
        <Text size="xSmall" className="date">{formatDate(record.date)}</Text>
      </Box>
      <Text bold style={{ color: isEarn ? '#2a9d8f' : '#e63946' }}>
        {isEarn ? '+' : ''}{record.point_amount.toLocaleString()} điểm
      </Text>
    </Box>
  );
}

function transactionLabel(type: string): string {
  const map: Record<string, string> = {
    earn: 'Tích điểm từ đơn hàng',
    exchange: 'Đổi điểm',
    manual: 'Điều chỉnh thủ công',
    return: 'Hoàn điểm',
  };
  return map[type] ?? 'Giao dịch khác';
}
```

---

### 8.3 VouchersPage — Danh sách Voucher

**Dữ liệu**: `getVouchers(partner_id)`

**Hiển thị**:
- Tabs: Đang có / Đã dùng / Hết hạn
- Mỗi voucher: code, loại giảm (%), giá trị, ngày hết hạn
- Nút "Sao chép code" (clipboard)
- Badge trạng thái màu

```tsx
// src/components/VoucherCard.tsx
export default function VoucherCard({ voucher }: { voucher: Voucher }) {
  const copy = () => navigator.clipboard.writeText(voucher.code);
  return (
    <Box className={`voucher-card state-${voucher.state}`}>
      <Box className="voucher-left">
        <Text bold size="xLarge" className="discount">
          {voucher.discount_type === 'percent'
            ? `-${voucher.discount_value}%`
            : `-${(voucher.discount_value / 1000).toFixed(0)}K`}
        </Text>
        <Text size="xSmall">{voucher.package_name}</Text>
      </Box>
      <Box className="voucher-right">
        <Text size="small" bold className="code">{voucher.code}</Text>
        {voucher.date_expiry && (
          <Text size="xSmall">HSD: {formatDate(voucher.date_expiry)}</Text>
        )}
        {voucher.state === 'active' && (
          <Button size="small" onClick={copy}>Sao chép</Button>
        )}
      </Box>
    </Box>
  );
}
```

---

### 8.4 RedeemPage — Đổi điểm

> **Lưu ý**: Đổi điểm qua Portal (session-based). Mini App không thể dùng trực tiếp các endpoint `/loyalty/redeem/*` vì chúng trả về HTML và dùng session cookie.
>
> **Giải pháp**: Mở WebView đến portal URL, hoặc yêu cầu backend tạo thêm endpoint JSON riêng (xem mục 10).

**Giải pháp ngắn hạn — Mở WebView**:

```tsx
// src/pages/RedeemPage.tsx
import { openWebview } from 'zmp-sdk/apis';

export default function RedeemPage() {
  const { partner } = usePartner();
  
  const openPortal = (tab: string) => {
    openWebview({
      url: `https://<domain>/loyalty/redeem?tab=${tab}`,
      config: {
        style: 'modal',
        headerColor: '#e63946',
        title: 'Đổi điểm',
      },
    });
  };

  return (
    <Page>
      <Box className="redeem-options">
        <Text.Title>Đổi điểm</Text.Title>
        <Text>Bạn có {partner?.total_points?.toLocaleString()} điểm</Text>
        
        <Button onClick={() => openPortal('gift')}>🎁 Đổi quà tặng</Button>
        <Button onClick={() => openPortal('cash')}>💵 Quy đổi tiền mặt</Button>
        <Button onClick={() => openPortal('history')}>📋 Lịch sử đổi điểm</Button>
      </Box>
    </Page>
  );
}
```

---

### 8.5 ProfilePage — Thông tin cá nhân

**Dữ liệu**: `getPartner(partner_id)`

**Hiển thị**:
- Avatar, tên, SĐT, email
- Hạng hiện tại + quyền lợi (`tier.benefits[]`)
- Nút "Đăng xuất" (xóa `localStorage`)
- Nút "Xem tất cả hạng thành viên" → TiersPage

---

### 8.6 TiersPage — Các hạng thành viên

**Dữ liệu**: `getTiers()`

**Hiển thị**:
- Danh sách tất cả hạng: ảnh, tên, điểm tối thiểu, quyền lợi
- Highlight hạng hiện tại của user

---

## 9. Navigation Structure

```
app-config.json (tabBar):
├── Tab 1: Trang chủ       → /           (HomePage)
├── Tab 2: Lịch sử         → /history    (HistoryPage)
├── Tab 3: Voucher         → /vouchers   (VouchersPage)
└── Tab 4: Cá nhân         → /profile    (ProfilePage)

Stack pages (navigate programmatically):
└── /redeem    (RedeemPage)
└── /tiers     (TiersPage)
└── /not-found (NotRegisteredPage)
```

```json
// app-config.json
{
  "app": {
    "title": "HLV Loyalty",
    "statusBar": {
      "color": "#e63946",
      "type": "transparent"
    }
  },
  "tabBar": {
    "custom": false,
    "backgroundColor": "#ffffff",
    "textColor": "#333",
    "selectedColor": "#e63946",
    "list": [
      { "pageSource": "pages/index", "label": "Trang chủ", "icon": "zi-home" },
      { "pageSource": "pages/history", "label": "Lịch sử", "icon": "zi-clock" },
      { "pageSource": "pages/vouchers", "label": "Voucher", "icon": "zi-label" },
      { "pageSource": "pages/profile", "label": "Cá nhân", "icon": "zi-user" }
    ]
  }
}
```

---

## 10. Danh sách đầy đủ các Endpoint

### 10.1 External Public API — dùng cho Zalo Mini App

Base URL: `https://<domain>`  
Auth: **Không cần** (auth='public')  
Content-Type: `application/json`

| # | Method | Endpoint | Params / Body | Mô tả |
|---|---|---|---|---|
| 1 | GET | `/api/v1/loyalty/tiers` | — | Danh sách tất cả hạng thành viên |
| 2 | GET | `/api/v1/loyalty/tiers/<id>/image` | — | Ảnh hạng (binary) |
| 3 | GET | `/api/v1/loyalty/partner/lookup` | `?phone=` hoặc `?email=` | Tìm partner theo SĐT/email |
| 4 | GET | `/api/v1/loyalty/partner/<id>` | — | Thông tin đầy đủ: điểm, hạng, voucher, lịch sử 10 gần nhất |
| 5 | GET | `/api/v1/loyalty/partner/<id>/history` | `?limit=20&offset=0` | Lịch sử giao dịch (phân trang) |
| 6 | GET | `/api/v1/loyalty/partners/<id>/image` | — | Ảnh đại diện partner (binary) |
| 7 | GET | `/api/v1/loyalty/vouchers/<id>` | `?state=active\|used\|expired` | Danh sách voucher của partner |
| 8 | POST | `/api/v1/loyalty/voucher/validate` | JSON-RPC body | Kiểm tra mã voucher |
| 9 | POST | `/api/v1/loyalty/points/add` | JSON-RPC body | Cộng/trừ điểm thủ công |

#### Request / Response chi tiết

**3. GET /api/v1/loyalty/partner/lookup**
```
GET /api/v1/loyalty/partner/lookup?phone=0901234567
Response 200:
{
  "id": 42,
  "name": "Nguyễn Văn A",
  "phone": "0901234567",
  "email": "a@example.com",
  "total_points": 1500,
  "image_url": "/api/v1/loyalty/partners/42/image",
  "tier": { "id": 2, "name": "Bạc", "min_points": 1000, ... },
  "next_tier": { "id": 3, "name": "Vàng", "min_points": 3000, ... },
  "points_to_next": 1500
}
Response 404: { "error": "Không tìm thấy khách hàng" }
```

**4. GET /api/v1/loyalty/partner/\<id\>**
```
Response 200:
{
  ...PartnerSummary,
  "active_vouchers": [
    { "id": 5, "code": "VHQ-ABC12", "discount_type": "percent",
      "discount_value": 10, "date_expiry": "2025-12-31T00:00:00" }
  ],
  "recent_history": [
    { "id": 101, "date": "2025-07-01T10:30:00",
      "point_amount": 200, "transaction_type": "earn",
      "description": "Tích điểm đơn SO/2025/001" }
  ]
}
```

**5. GET /api/v1/loyalty/partner/\<id\>/history**
```
Response 200:
{
  "partner_id": 42,
  "total_points": 1500,
  "total_records": 47,
  "limit": 20,
  "offset": 0,
  "records": [ ...HistoryRecord[] ]
}
```

**8. POST /api/v1/loyalty/voucher/validate** (JSON-RPC)
```json
// Request
{
  "jsonrpc": "2.0", "method": "call", "id": 1,
  "params": {
    "code": "VHQ-ABC12",
    "partner_id": 42,
    "order_amount": 500000
  }
}
// Response (result)
{
  "valid": true,
  "voucher": {
    "id": 5, "code": "VHQ-ABC12",
    "discount_type": "percent", "discount_value": 10,
    "estimated_discount": 50000,
    "date_expiry": "2025-12-31T00:00:00",
    "partner_id": 42, "partner_name": "Nguyễn Văn A"
  }
}
// Response (lỗi)
{ "valid": false, "error": "Voucher đã hết hạn" }
```

**9. POST /api/v1/loyalty/points/add** (JSON-RPC)
```json
// Request
{
  "jsonrpc": "2.0", "method": "call", "id": 1,
  "params": {
    "partner_id": 42,
    "points": 100,
    "description": "Cộng điểm sinh nhật"
  }
}
// Response
{
  "success": true,
  "partner_id": 42,
  "partner_name": "Nguyễn Văn A",
  "points_added": 100,
  "total_points": 1600,
  "tier": { ... }
}
```

---

### 10.2 Portal API (session-based, HTML) — không dùng trực tiếp trong ZMA

> Các endpoint dưới đây trả về HTML và dùng session cookie. Trong Zalo Mini App, mở qua `openWebview()` hoặc tạo API JSON mới.

| Method | Endpoint | Mô tả |
|---|---|---|
| GET | `/loyalty` | Trang chủ portal (redirect login/dashboard) |
| POST | `/loyalty/login` | Đăng nhập (`login`, `password`) |
| GET/POST | `/loyalty/logout` | Đăng xuất |
| GET | `/loyalty/dashboard` | Dashboard |
| POST | `/loyalty/change-phone` | Đổi SĐT (`new_phone`) |
| POST | `/loyalty/change-password` | Đổi mật khẩu |
| GET | `/loyalty/history` | Lịch sử (`pt`, `st` filter) |
| GET | `/loyalty/redeem` | Trang đổi điểm (`tab=gift/cash/history`) |
| POST | `/loyalty/redeem/gift` | Submit đổi quà (`package_id`) |
| POST | `/loyalty/redeem/cash` | Submit đổi tiền mặt |
| GET | `/loyalty/vouchers` | Danh sách voucher |

### 10.3 Internal API (auth=Odoo user/API key) — không dùng trong ZMA

| Method | Endpoint | Mô tả |
|---|---|---|
| GET | `/api/loyalty/points/<id>` | Điểm partner |
| GET | `/api/loyalty/history/<id>` | Lịch sử |
| GET | `/api/loyalty/vouchers/<id>` | Voucher |
| POST | `/api/loyalty/redeem` | Đổi voucher (package_id) |
| POST | `/api/loyalty/validate-voucher` | Validate voucher code |

---

## 11. Yêu cầu thêm endpoint JSON cho Đổi điểm (roadmap)

Để cho phép Mini App thực hiện đổi điểm không qua WebView, cần thêm 2 endpoint vào `loyalty_api.py`:

### 11.1 Lấy danh sách gói đổi điểm

```
GET /api/v1/loyalty/redeem/packages
Response:
[
  {
    "id": 1,
    "name": "Voucher 50K",
    "points_required": 500,
    "description": "...",
    "image_url": "...",
    "type": "gift"         // "gift" | "cash"
  }
]
```

### 11.2 Submit đổi điểm (tạo reward request)

```
POST /api/v1/loyalty/redeem/submit  (JSON-RPC)
Body params:
{
  "partner_id": 42,
  "package_id": 1,               // cho gift
  "points_to_redeem": 500,       // cho cash
  "bank_name": "Vietcombank",    // cho cash
  "account_number": "1234567890",
  "account_name": "NGUYEN VAN A",
  "customer_note": "..."
}
Response:
{
  "success": true,
  "request_id": 15,
  "message": "Yêu cầu đổi điểm đã được gửi thành công"
}
```

---

## 12. Utility Functions

```typescript
// src/utils/format.ts

export function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

export function formatPoints(n: number): string {
  return n.toLocaleString('vi-VN') + ' điểm';
}

export function formatCurrency(n: number): string {
  return n.toLocaleString('vi-VN') + ' ₫';
}

export function transactionTypeLabel(type: string): string {
  const map: Record<string, string> = {
    earn: '🟢 Tích điểm',
    exchange: '🔴 Đổi điểm',
    manual: '🔵 Điều chỉnh',
    return: '🟡 Hoàn điểm',
  };
  return map[type] ?? '⚪ Khác';
}
```

---

## 13. Error Handling

```typescript
// src/api/loyalty.ts — global error handler
api.interceptors.response.use(
  res => res,
  err => {
    const status = err.response?.status;
    if (status === 404) throw new Error('Không tìm thấy dữ liệu');
    if (status === 400) throw new Error(err.response?.data?.error ?? 'Yêu cầu không hợp lệ');
    throw new Error('Lỗi kết nối máy chủ. Vui lòng thử lại.');
  }
);

// Trong component, bắt lỗi và hiển thị snackbar:
try {
  const data = await getHistory(partnerId);
} catch (e: any) {
  showSnackbar({ text: e.message, type: 'error' });
}
```

---

## 14. Checklist triển khai

- [ ] Tạo project ZMP: `npm create zmp-app@latest`
- [ ] Cấu hình `BASE_URL` trong `src/api/loyalty.ts`
- [ ] Implement auth flow với `getUserInfo()` + `lookupPartnerByPhone()`
- [ ] Xây dựng `HomePage` với điểm + hạng + recent history
- [ ] Xây dựng `HistoryPage` với infinite scroll
- [ ] Xây dựng `VouchersPage` với tabs + copy code
- [ ] Xây dựng `RedeemPage` (WebView hoặc JSON endpoint nếu đã thêm)
- [ ] Xây dựng `ProfilePage` + `TiersPage`
- [ ] Cấu hình `app-config.json` tabBar
- [ ] Xử lý trường hợp SĐT chưa đăng ký
- [ ] Test trên Zalo app (scan QR từ IDE)
- [ ] Submit lên Zalo Mini App Store

---

## 15. Lưu ý bảo mật

- Endpoint `/api/v1/loyalty/points/add` (POST) hiện là `auth='public'` — **cần bảo vệ** bằng API key hoặc secret header trước khi production:
  ```
  Header: X-Loyalty-Secret: <your_secret_key>
  ```
  Thêm xác thực vào controller Odoo để kiểm tra header này.
- Không lưu thông tin nhạy cảm (số tài khoản ngân hàng) trong localStorage.
- Dùng HTTPS cho tất cả request đến Odoo.
- `partner_id` từ ZMP chỉ cần tra cứu theo SĐT đã được Zalo xác thực — không cho phép user tự nhập `partner_id`.
