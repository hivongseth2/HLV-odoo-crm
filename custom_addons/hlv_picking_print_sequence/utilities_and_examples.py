"""
HLV Picking Print Sequence - Utilities and Examples
=====================================================

Các hàm tiện ích và ví dụ sử dụng module.
"""

# ============================================================================
# 1. SẮP XẾP STANDARD/THÔNG THƯỜNG
# ============================================================================

def example_manual_sequence():
    """Sắp xếp thủ công bằng code"""
    pickings = env['stock.picking'].browse([1, 2, 3, 4, 5])
    picking_ids = [2, 1, 5, 3, 4]  # Thứ tự mong muốn
    
    for idx, picking_id in enumerate(picking_ids, 1):
        picking = env['stock.picking'].browse(picking_id)
        picking.print_sequence = idx


# ============================================================================
# 2. BẰNG NGÀY TẠO (CŨ TRƯỚC, MỚI SAU)
# ============================================================================

def example_auto_sequence_by_date():
    """Tự động sắp xếp theo ngày tạo"""
    pickings = env['stock.picking'].search([
        ('picking_type_id.code', '=', 'outgoing'),
        ('state', 'in', ['waiting', 'confirmed', 'assigned'])
    ], order='create_date asc')
    
    for idx, picking in enumerate(pickings, 1):
        picking.print_sequence = idx


# ============================================================================
# 3. BẰNG NGÀY DỰ KIẾN (DUE DATE)
# ============================================================================

def example_sequence_by_due_date():
    """Sắp xếp theo ngày giao dịch (sớm trước)"""
    pickings = env['stock.picking'].search([], order='scheduled_date asc')
    
    for idx, picking in enumerate(pickings, 1):
        picking.print_sequence = idx


# ============================================================================
# 4. BẰNG ĐỊA CHỈ / WAREHOUSE
# ============================================================================

def example_sequence_by_warehouse():
    """Sắp xếp theo kho / địa điểm"""
    pickings = env['stock.picking'].search([
        ('state', '=', 'done')
    ], order='location_dest_id, create_date asc')
    
    sequence = 1
    current_warehouse = None
    
    for picking in pickings:
        if current_warehouse != picking.location_dest_id:
            current_warehouse = picking.location_dest_id
            sequence = 1  # Reset sequence cho kho mới
        
        picking.print_sequence = sequence
        sequence += 1


# ============================================================================
# 5. BẰNG CUSTOMER / PARTNER
# ============================================================================

def example_sequence_by_customer():
    """Sắp xếp theo khách hàng (từ A-Z)"""
    pickings = env['stock.picking'].search(
        [],
        order='partner_id, create_date asc'
    )
    
    for idx, picking in enumerate(pickings, 1):
        picking.print_sequence = idx


# ============================================================================
# 6. BẰNG PRIORITY
# ============================================================================

def example_sequence_by_priority():
    """Sắp xếp theo ưu tiên (cao trước)"""
    pickings = env['stock.picking'].search([], order='priority desc, create_date asc')
    
    for idx, picking in enumerate(pickings, 1):
        picking.print_sequence = idx


# ============================================================================
# 7. LỌCU PHIẾU CÓ SEQUENCE & IN
# ============================================================================

def example_filter_and_print():
    """Lọc phiếu có sequence và in"""
    pickings = env['stock.picking'].search([
        ('print_sequence', '>', 0),
        ('state', '=', 'done')
    ], order='print_sequence asc')
    
    # In theo thứ tự
    return {
        'type': 'ir.actions.report',
        'report_name': 'stock.report_picking',
        'ids': pickings.ids,
    }


# ============================================================================
# 8. BATCH PROCESSING - SẮP XẾP HÀNG LOẠT THEO NGÀY
# ============================================================================

def example_batch_daily_sequence():
    """
    Sắp xếp hàng loạt: Mỗi ngày là một batch, 
    mỗi batch sắp xếp riêng từ 1 đến N
    """
    from datetime import datetime, timedelta
    
    # Lấy tất cả phiếu chưa in
    all_pickings = env['stock.picking'].search([
        ('print_sequence', '=', 0),
        ('state', '=', 'done')
    ], order='create_date asc')
    
    # Nhóm theo ngày
    days = {}
    for picking in all_pickings:
        day = picking.create_date.date()
        if day not in days:
            days[day] = []
        days[day].append(picking)
    
    # Sắp xếp từng ngày
    for day in sorted(days.keys()):
        pickings_of_day = days[day]
        for idx, picking in enumerate(pickings_of_day, 1):
            picking.print_sequence = idx


# ============================================================================
# 9. CUSTOM SEQUENCE RULE - VỊ TRÍ + NGÀY
# ============================================================================

def example_sequence_location_then_date():
    """
    Sắp xếp: Địa điểm đó -> Ngày cũ trước -> Ngày mới sau
    Dùng khi cần in theo từng khu vực rồi từng ngày
    """
    pickings = env['stock.picking'].search(
        [('state', '=', 'done')],
        order='location_id, create_date asc'
    )
    
    sequence = 1
    last_location = None
    
    for picking in pickings:
        if last_location != picking.location_id:
            last_location = picking.location_id
        
        picking.print_sequence = sequence
        sequence += 1


# ============================================================================
# 10. SKIP BLACKLIST ITEMS
# ============================================================================

def example_skip_certain_pickings():
    """Sắp xếp nhưng bỏ qua những phiếu nhất định"""
    
    # Những loại phiếu cần bỏ qua (có thể là return, defect, etc)
    skip_states = ['cancel']
    skip_types = ['incoming']  # Bỏ qua phiếu nhập kho
    
    pickings = env['stock.picking'].search([
        ('state', 'not in', skip_states),
        ('picking_type_id.code', '!=', skip_types[0]),
    ], order='create_date asc')
    
    for idx, picking in enumerate(pickings, 1):
        picking.print_sequence = idx


# ============================================================================
# 11. RESET VÀ SẮP XẾP LẠI
# ============================================================================

def example_reset_then_resequence():
    """Xóa tất cả sequence rồi sắp xếp lại"""
    
    # Bước 1: Reset
    all_pickings = env['stock.picking'].search([
        ('print_sequence', '>', 0)
    ])
    all_pickings.write({'print_sequence': 0})
    
    # Bước 2: Sắp xếp lại
    pickings = env['stock.picking'].search([], order='create_date asc')
    for idx, picking in enumerate(pickings, 1):
        picking.print_sequence = idx


# ============================================================================
# 12. REPORT WITH SEQUENCE
# ============================================================================

def example_report_with_sequence():
    """Report chiếc phiếu theo thứ tự in"""
    
    xml_template = '''
    <t>
        <t t-foreach="docs" t-as="picking">
            <t t-if="picking.print_sequence > 0">
                <div class="picking-entry">
                    <h4>Thứ tự in: <t t-esc="picking.print_sequence"/></h4>
                    <p>Phiếu: <t t-esc="picking.name"/></p>
                </div>
            </t>
        </t>
    </t>
    '''
    
    return {
        'type': 'ir.actions.report',
        'report_name': 'hlv_picking_print_sequence.report_picking_with_sequence',
        'report_type': 'qweb-pdf',
    }


# ============================================================================
# 13. CRON JOB - TỰ ĐỘNG ĐÁNH SỐ MỖI HÔM
# ============================================================================

def setup_cron_auto_sequence():
    """
    Tạo cron job tự động sắp xếp phiếu mỗi sáng
    
    Chèn vào __manifest__.py:
    'data': [
        'data/cron_jobs.xml',
    ]
    
    Nội dung data/cron_jobs.xml:
    """
    
    cron_xml = '''
    <odoo>
        <data noupdate="1">
            <!-- Auto-sequence pickings every morning -->
            <record id="ir_cron_auto_sequence_picking" model="ir.cron">
                <field name="name">Auto Sequence Pickings</field>
                <field name="model_id" ref="stock.model_stock_picking"/>
                <field name="state">code</field>
                <field name="code">
# Tự động đánh số phiếu mỗi sáng lúc 7h
model = env['stock.picking']
pickings = model.search([
    ('print_sequence', '=', 0),
    ('state', 'in', ['waiting', 'confirmed', 'assigned'])
])

if pickings:
    sorted_pickings = pickings.sorted(key=lambda p: p.create_date)
    for idx, picking in enumerate(sorted_pickings, 1):
        picking.print_sequence = idx
                </field>
                <field name="interval_number">1</field>
                <field name="interval_type">days</field>
                <field name="nextcall">2024-01-15 07:00:00</field>
            </record>
        </data>
    </odoo>
    '''
    
    return cron_xml


# ============================================================================
# 14. VALIDATION - KIỂM TRA DUPLICATE SEQUENCE
# ============================================================================

def validate_no_duplicate_sequence():
    """Kiểm tra không có phiếu trùng sequence"""
    
    pickings = env['stock.picking'].search([
        ('print_sequence', '>', 0)
    ])
    
    sequences = {}
    duplicates = []
    
    for picking in pickings:
        seq = picking.print_sequence
        if seq in sequences:
            duplicates.append((seq, picking.name))
        else:
            sequences[seq] = picking.name
    
    if duplicates:
        raise ValueError(f"Phát hiện sequence trùng lặp: {duplicates}")
    
    return True


# ============================================================================
# 15. EXPORT PRINT ORDER
# ============================================================================

def export_print_order_to_csv():
    """Export danh sách phiếu theo thứ tự in"""
    import csv
    
    pickings = env['stock.picking'].search([
        ('print_sequence', '>', 0),
        ('state', '=', 'done')
    ], order='print_sequence asc')
    
    csv_data = [['Sequence', 'Picking', 'Partner', 'Date']]
    
    for picking in pickings:
        csv_data.append([
            picking.print_sequence,
            picking.name,
            picking.partner_id.name,
            picking.create_date.strftime('%Y-%m-%d'),
        ])
    
    return csv_data


# ============================================================================
# MIGRATION GUIDE - DỮ LIỆU CŨ
# ============================================================================

"""
Nếu có dữ liệu picking cũ, có thể migrate như sau:

1. Lấy tất cả picking đã done
2. Sắp xếp theo ngày
3. Gán sequence tăng dần

Ví dụ:
"""

def migrate_old_pickings():
    """Migrate dữ liệu picking cũ với sequence"""
    
    # Lấy tất cả picking đã hoàn tất, chưa có sequence
    old_pickings = env['stock.picking'].search([
        ('print_sequence', '=', 0),
        ('state', '=', 'done'),
    ], order='date_done asc')
    
    print(f"Migrating {len(old_pickings)} picking records...")
    
    for idx, picking in enumerate(old_pickings, 1):
        picking.print_sequence = idx
        if idx % 100 == 0:
            print(f"  Processed {idx} records...")
    
    print(f"Migration complete! Total: {len(old_pickings)}")
