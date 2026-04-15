# Design System Document: High-End Loyalty Editorial

## 1. Overview & Creative North Star
**Creative North Star: "The Sovereign Curator"**

This design system moves away from the utilitarian, grid-locked nature of standard loyalty dashboards. It adopts an editorial philosophy where space is a luxury and hierarchy is dictated by tonal depth rather than structural lines. By utilizing intentional asymmetry, overlapping card components, and a sophisticated "Glass-on-Gradient" aesthetic, we transform a transactional loyalty program into a premium membership experience.

The system breaks the "template" look by treating the interface as a series of curated layers. We avoid the "boxed-in" feel of traditional web apps, opting instead for a fluid, high-contrast environment where the deep primary blue acts as a nocturnal canvas for gold accents and crisp, geometric typography.

---

## 2. Colors & Surface Philosophy
The palette is rooted in a high-contrast relationship between deep midnight blues and luminous gold metallics, designed to evoke trust and exclusivity.

### Palette Strategy
*   **Primary (`#000666`) to Primary-Container (`#1a237e`):** Used for large-scale immersive backgrounds and hero headers.
*   **Secondary (`#765a22`) & Tertiary (`#251800`):** These are your "Gold" tokens. Use them for high-value accents, tier status indicators, and call-to-action highlights.
*   **Neutrals:** A range of `surface-container` tiers from Lowest (`#ffffff`) to Highest (`#e1e3e4`) to facilitate tonal layering.

### The "No-Line" Rule
**Explicit Instruction:** Prohibition of 1px solid borders for sectioning. 
Boundaries must be defined solely through background color shifts. For example, a `surface-container-lowest` card should sit on a `surface-container-low` background. The transition of color is the border.

### Signature Textures: Glass & Gradients
To move beyond a flat digital feel:
*   **The Signature Gradient:** Linear gradient from `primary` (#000666) to a custom blend of `on_primary_container` (#8690ee) and `secondary` (#765a22) at a 135-degree angle. This should be used for the Hero/Membership Status header.
*   **Glassmorphism:** Floating elements (like the current points balance) must use semi-transparent `surface` colors with a `backdrop-blur` (12px–20px). This creates "visual soul" by allowing the underlying gradient to bleed through softly.

---

## 3. Typography: The Editorial Voice
We use a dual-sans-serif approach to balance authority with modern readability.

*   **The Voice (Manrope):** Used for `display` and `headline` scales. Manrope’s geometric yet warm proportions provide an authoritative, premium feel.
    *   *Usage:* Use `display-lg` (3.5rem) for point balances and `headline-md` (1.75rem) for section titles.
*   **The Information (Inter):** Used for `title`, `body`, and `label` scales. Inter provides maximum legibility for transactional data and tier benefits.
    *   *Usage:* `title-md` (1.125rem) for card headings; `body-sm` (0.75rem) for fine-print terms.

**Intentional Scale:** We utilize high-contrast sizing. A `display-lg` value sitting near a `label-md` creates a "Big-and-Small" editorial tension that feels intentional and high-end.

---

## 4. Elevation & Depth: Tonal Layering
Traditional dropshadows are largely replaced by "The Layering Principle."

*   **Stacking Tiers:** 
    1.  Base: `background` (#f8f9fa)
    2.  Section: `surface-container-low` (#f3f4f5)
    3.  Card: `surface-container-lowest` (#ffffff)
*   **Ambient Shadows:** When a "floating" effect is required for a Diamond-tier modal or a primary CTA, use an extra-diffused shadow: `box-shadow: 0 20px 40px rgba(0, 7, 103, 0.06)`. Note the use of a tinted shadow (using the `on_primary_fixed` color) rather than neutral grey.
*   **The Ghost Border:** If accessibility requires a stroke (e.g., in high-contrast mode), use `outline-variant` at 15% opacity. Never use 100% opaque borders.

---

## 5. Components

### Membership Tier Cards
Forbid standard list items. Tiers (Bronze, Silver, Gold, Diamond) should be represented as expansive cards using `surface-container-lowest`.
*   **Status Indicators:** Use `secondary_container` (#ffd793) for Gold and a semi-transparent `primary_fixed` (#e0e0ff) for Diamond. 
*   **Asymmetry:** Place the tier icon (e.g., a geometric emblem) partially breaking the top-left boundary of the card to create a custom, non-templated look.

### Buttons & CTAs
*   **Primary:** Background of `primary`, text in `on_primary`. Apply `md` (0.375rem) rounding.
*   **Premium Action:** Use a gradient fill from `secondary` (#765a22) to `on_secondary_container` (#795c25) to denote "Redeem" or "Upgrade" actions.

### Inputs & Progress Bars
*   **Tier Progress:** Replace standard thin progress bars with a wide, `xl` (0.75rem) rounded track. Use `surface-variant` for the track and a `secondary` to `secondary_fixed` gradient for the fill.
*   **Input Fields:** No borders. Use `surface-container-high` as a solid fill with a `label-sm` floating above it.

### Lists & Activity
*   **Forbid Dividers:** Separate "Recent Transactions" using 24px of vertical whitespace or subtle alternating backgrounds (`surface` to `surface-container-low`).

---

## 6. Do’s and Don’ts

### Do:
*   **Do** use extreme white space. If you think there is enough padding, add 8px more.
*   **Do** overlap elements. A "Glass" card should partially sit over the "Primary" gradient header.
*   **Do** use "Tonal Shifts" for hover states. Instead of a border, change a card from `surface-container-lowest` to `surface-bright` on hover.

### Don't:
*   **Don't** use pure black (#000000) for text. Always use `on_surface` (#191c1d) for a softer, premium contrast.
*   **Don't** use 1px solid lines to separate content. It breaks the "Sovereign Curator" illusion and makes the UI look like a spreadsheet.
*   **Don't** use standard "Success" green for positive point updates. Use the `secondary` gold or `primary` blue to maintain the brand’s sophisticated palette.