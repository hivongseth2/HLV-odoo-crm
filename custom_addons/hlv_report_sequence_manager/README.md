# HLV Report Sequence Manager

## Overview

This module allows you to **control the order of print templates** that appear in the print dropdown menu. You can easily drag-and-drop to reorder templates and make your most-used reports appear first.

## Features

✅ **Add Sequence Field** - Each print template now has a sequence number
✅ **Drag-and-Drop Reordering** - Intuitive drag-and-drop in the list view
✅ **Group by Model** - Organize templates by the model they belong to
✅ **Search and Filter** - Find templates by name, model, or report type
✅ **Quick Access Menu** - Dedicated menu under Stock Configuration

## How It Works

### What Gets Changed?

The sequence of print templates (ir.actions.report records) is now managed through a **Sequence** field:

- Each print template (report) gets a **sequence number**
- Lower numbers = higher in the dropdown menu
- The system sorts all print templates by sequence automatically

### Default Sequence

- All existing print templates start with sequence = 10
- New templates get sequence = 10 by default
- If multiple templates have the same sequence, they're sorted by name

## Usage

### Method 1: Drag-and-Drop (Fastest)

1. Go to **Stock > Configuration > Print Templates Order**
2. See all print templates in a list
3. **Drag the handle icon (☰)** to reorder templates
4. Changes save automatically

### Method 2: Form Edit

1. Go to **Stock > Configuration > Print Templates Order**
2. Click on any template name to open the form
3. Change the **Sequence** field (lower = higher in menu)
4. Click **Save**

### Method 3: Bulk Edit

1. Select multiple templates in the list
2. Edit the **Sequence** field directly
3. Changes apply to all selected templates

### Method 4: Group and Filter

1. Go to **Stock > Configuration > Print Templates Order**
2. Use **Group By** dropdown to organize by:
   - **Model** - See templates grouped by the document type
   - **Report Type** - Group by QWeb PDF, Python, etc.
3. Use filters to show only specific template types

## Examples

### Example 1: Prioritize Delivery Note

**Goal**: Make "Phiếu giao hàng" appear first when printing

**Steps**:
1. Open **Print Templates Order** menu
2. Find "Phiếu giao hàng" template
3. Change its sequence from 10 to **1**
4. Click Save
5. Done! Now it appears first in print dropdown

### Example 2: Group Related Templates

**Goal**: Keep all invoice templates together at the top

**Steps**:
1. Find all invoice-related templates
2. Set their sequence to: **10, 11, 12, 13**
3. Set other templates to: **20, 21, 22, 23**
4. Now invoices appear first, then others

### Example 3: Hide Low-Used Templates

**Workaround** (since we can't truly hide):
- Set rarely-used templates to very high sequence numbers (999, 1000)
- They'll appear at the very bottom of the dropdown

## Technical Details

### Model Extended
- **Model**: `ir.actions.report`
- **Field Added**: `sequence` (Integer, default=10)

### Views Created
1. **Form View** - Edit sequence alongside other report settings
2. **List View** - Drag-and-drop reordering with handle
3. **Search View** - Find templates by name, model, or type

### Menu Location
**Stock > Configuration > Print Templates Order**

### Database Changes
- New field `sequence` on `ir.actions.report` table
- No destructive changes to existing templates

## Important Notes

⚠️ **Affects All Reports**
- This module affects ALL print templates in your Odoo instance
- Changes apply globally to all users

⚠️ **Sequence vs Menu Order**
- This controls the order in **dropdown menus** where you print from
- Menu items themselves are managed separately (you can also reorder those in Settings > Technical > Menu Items)

⚠️ **Default Order**
- If you don't set sequences, templates appear in the order they were created
- Setting even one sequence to a low number will affect the overall order

## Troubleshooting

### Templates not showing in expected order?
1. Check the **Sequence** values (lower = higher)
2. Make sure you **saved** your changes
3. Reload the page (F5) to see the updated order
4. Check if there are multiple buttons/templates with the same name

### Can't find a specific template?
1. Use the **search field** at the top of the list
2. Try searching by the document type (e.g., "Picking")
3. Use **Group By Model** to see what's available

### Changed sequence but order didn't update?
1. Make sure you **saved** the changes
2. Odoo caches menus - **clear browser cache** or open private window
3. Try **reloading the page** (Ctrl+Shift+R for hard refresh)

## Version History

### v18.0.1.0.0
- Initial release
- Add sequence field to ir.actions.report
- Create management views with drag-and-drop
- Add menu under Stock Configuration

## Support

For issues or questions about print template ordering, check:
1. The **Manage Print Templates** menu
2. Search for templates by model
3. Verify sequence numbers are numeric and reasonable (0-999)
