# Warehouse Access Control Fix

## Vấn đề đã khắc phục

Trước đây, hệ thống warehouse access control chỉ áp dụng cho việc lọc vị trí nguồn (source locations) trong các thao tác assembly và disassembly. Tuy nhiên, người dùng vẫn có thể chọn vị trí đích (destination locations) nằm ngoài warehouse mà họ được phép truy cập.

## Giải pháp

### 1. Thêm Computed Field cho Destination Locations

Đã thêm field `available_destination_location_ids` vào model `production.operation`:

```python
available_destination_location_ids = fields.Many2many(
    'stock.location',
    compute='_compute_available_destination_locations',
    string='Vị trí đích có sẵn'
)
```

### 2. Implement Access Control Logic

Tạo method `_get_user_accessible_locations()` để lấy danh sách vị trí mà user được phép truy cập:

```python
def _get_user_accessible_locations(self):
    """Get locations that current user has access to"""
    current_user = self.env.user
    
    # Check if user is stock manager (has full access)
    if current_user.has_group('stock.group_stock_manager'):
        return self.env['stock.location'].search([('usage', 'in', ['internal', 'transit'])])
    
    # Get accessible locations from warehouse access config
    warehouse_config = self.env['warehouse.access.config']
    return warehouse_config.get_accessible_locations(current_user.id)
```

### 3. Domain Filter trong View

Cập nhật view để áp dụng domain filter cho destination location:

```xml
<field name="destination_location_id" 
       domain="[('id', 'in', available_destination_location_ids)]"
       options="{'no_create': True, 'no_create_edit': True}"/>
```

### 4. Validation Constraints

Thêm constraint để ngăn chặn việc chọn vị trí không được phép:

```python
@api.constrains('destination_location_id', 'source_location_id')
def _check_location_access(self):
    """Check if user has access to selected locations"""
    for record in self:
        accessible_locations = record._get_user_accessible_locations()
        
        # Check destination location access for assembly
        if record.operation_type == 'assembly' and record.destination_location_id:
            if record.destination_location_id not in accessible_locations:
                raise ValidationError(_('Bạn không có quyền truy cập vào vị trí đích đã chọn: %s') % record.destination_location_id.display_name)
```

### 5. Cập nhật Component Lines

Cũng áp dụng access control cho component lines:

```python
@api.constrains('source_location_id')
def _check_location_access(self):
    """Check if user has access to selected location"""
    for line in self:
        if line.source_location_id:
            warehouse_config = self.env['warehouse.access.config']
            accessible_locations = warehouse_config.get_accessible_locations(self.env.user.id)
            
            if line.source_location_id not in accessible_locations:
                raise ValidationError(_('Bạn không có quyền truy cập vào vị trí đã chọn: %s') % line.source_location_id.display_name)
```

## Test Coverage

Đã tạo test suite comprehensive để kiểm tra:

1. **Assembly Destination Access Control**: Kiểm tra user không thể chọn destination location không được phép
2. **Disassembly Source Access Control**: Kiểm tra user không thể chọn source location không được phép  
3. **Component Line Access Control**: Kiểm tra access control trong component lines
4. **Available Locations Filtering**: Kiểm tra việc lọc locations dựa trên access control
5. **Admin User Access**: Kiểm tra admin users có quyền truy cập tất cả locations

## Tác động

### Trước khi fix:
- User với quyền TSN warehouse vẫn có thể chọn KBC warehouse locations làm destination
- Không có validation khi save record
- Có thể tạo stock moves với locations không được phép

### Sau khi fix:
- User chỉ thấy và chọn được locations trong warehouse được phép
- Validation error nếu cố gắng chọn location không được phép
- Đảm bảo tính nhất quán trong toàn bộ hệ thống

## Files Modified

1. `models/production_operation.py` - Thêm computed field và validation
2. `models/production_operation_line.py` - Thêm validation cho component lines  
3. `models/warehouse_access_config.py` - Cập nhật method calls với user_id
4. `views/production_operation_views.xml` - Thêm domain filter
5. `tests/test_location_access_control.py` - Test suite mới

## Backward Compatibility

Tất cả thay đổi đều backward compatible:
- Không thay đổi database schema
- Không ảnh hưởng đến existing data
- Admin users vẫn có full access như trước
- Users không có warehouse config vẫn hoạt động bình thường (không có access)