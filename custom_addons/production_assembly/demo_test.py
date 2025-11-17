#!/usr/bin/env python3
"""
Demo script để test module Production Assembly & Disassembly
Chạy script này trong Odoo shell để tạo dữ liệu demo
"""

def create_demo_data():
    """Tạo dữ liệu demo cho module production assembly"""
    
    # Tìm hoặc tạo sản phẩm demo
    Product = env['product.product']
    Location = env['stock.location']
    
    # Tạo sản phẩm thành phẩm
    finished_product = Product.create({
        'name': 'Demo Finished Product',
        'type': 'product',
        'categ_id': env.ref('product.product_category_all').id,
    })
    
    # Tạo sản phẩm thành phần
    component1 = Product.create({
        'name': 'Demo Component 1',
        'type': 'product',
        'categ_id': env.ref('product.product_category_all').id,
    })
    
    component2 = Product.create({
        'name': 'Demo Component 2', 
        'type': 'product',
        'categ_id': env.ref('product.product_category_all').id,
    })
    
    # Tìm locations
    stock_location = env.ref('stock.stock_location_stock')
    
    # Tạo initial stock cho components
    env['stock.quant'].create({
        'product_id': component1.id,
        'location_id': stock_location.id,
        'quantity': 100.0,
    })
    
    env['stock.quant'].create({
        'product_id': component2.id,
        'location_id': stock_location.id,
        'quantity': 50.0,
    })
    
    # Tạo assembly operation
    assembly_op = env['production.operation'].create({
        'operation_type': 'assembly',
        'main_product_id': finished_product.id,
        'main_product_qty': 10.0,
        'destination_location_id': stock_location.id,
        'component_line_ids': [
            (0, 0, {
                'product_id': component1.id,
                'qty': 20.0,
                'source_location_id': stock_location.id,
            }),
            (0, 0, {
                'product_id': component2.id,
                'qty': 10.0,
                'source_location_id': stock_location.id,
            }),
        ]
    })
    
    print(f"Created assembly operation: {assembly_op.name}")
    
    # Tạo disassembly operation
    disassembly_op = env['production.operation'].create({
        'operation_type': 'disassembly',
        'main_product_id': finished_product.id,
        'main_product_qty': 5.0,
        'destination_location_id': stock_location.id,
        'component_line_ids': [
            (0, 0, {
                'product_id': component1.id,
                'qty': 10.0,
                'source_location_id': stock_location.id,
            }),
            (0, 0, {
                'product_id': component2.id,
                'qty': 5.0,
                'source_location_id': stock_location.id,
            }),
        ]
    })
    
    print(f"Created disassembly operation: {disassembly_op.name}")
    
    return {
        'assembly_operation': assembly_op,
        'disassembly_operation': disassembly_op,
        'finished_product': finished_product,
        'components': [component1, component2]
    }

# Uncomment để chạy khi load script trong Odoo shell
# demo_data = create_demo_data()