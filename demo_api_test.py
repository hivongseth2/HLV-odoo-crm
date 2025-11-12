#!/usr/bin/env python3
"""
Demo script to test AI Sales Support API
"""
import requests
import json
import time

# Configuration
BASE_URL = "http://localhost:8069"  # Adjust as needed
API_BASE = f"{BASE_URL}/api/ai_sales"

def test_health_check():
    """Test health check endpoint"""
    print("Testing health check...")
    try:
        response = requests.get(f"{API_BASE}/health")
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Health check passed: {data}")
            return True
        else:
            print(f"✗ Health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Health check error: {e}")
        return False

def test_create_sales_request():
    """Test creating a sales request"""
    print("\nTesting sales request creation...")
    
    payload = {
        "sales_person": "Anh Quang",
        "sales_email": "quang@hlv.com",
        "customer_name": "Khách hàng ABC",
        "product_request": "Tôi cần 100 cái ốc vít M6x20mm inox 304"
    }
    
    try:
        response = requests.post(
            f"{API_BASE}/request",
            json=payload,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                print(f"✓ Sales request created: {data['request_id']}")
                return data['request_id']
            else:
                print(f"✗ Sales request failed: {data.get('error')}")
                return None
        else:
            print(f"✗ Sales request failed: {response.status_code}")
            return None
    except Exception as e:
        print(f"✗ Sales request error: {e}")
        return None

def test_get_request_status(request_id):
    """Test getting request status"""
    print(f"\nTesting request status for {request_id}...")
    
    try:
        response = requests.get(f"{API_BASE}/status/{request_id}")
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                print(f"✓ Request status: {data['status']}")
                print(f"  Sales person: {data.get('sales_person')}")
                print(f"  Customer: {data.get('customer_name')}")
                return data
            else:
                print(f"✗ Status check failed: {data.get('error')}")
                return None
        else:
            print(f"✗ Status check failed: {response.status_code}")
            return None
    except Exception as e:
        print(f"✗ Status check error: {e}")
        return None

def test_list_requests():
    """Test listing requests"""
    print("\nTesting request listing...")
    
    try:
        response = requests.get(f"{API_BASE}/requests?limit=5")
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                requests_list = data.get('requests', [])
                print(f"✓ Found {len(requests_list)} requests")
                for req in requests_list[:3]:  # Show first 3
                    print(f"  - {req['request_id']}: {req['status']} ({req['sales_person']})")
                return data
            else:
                print(f"✗ List requests failed: {data.get('error')}")
                return None
        else:
            print(f"✗ List requests failed: {response.status_code}")
            return None
    except Exception as e:
        print(f"✗ List requests error: {e}")
        return None

def test_webhook_simulation():
    """Test webhook simulation"""
    print("\nTesting webhook simulation...")
    
    payload = {
        "sender_id": "test_supplier_123",
        "message": "Giá 50,000 VND/cái, giao hàng trong 3 ngày, tối thiểu 50 cái"
    }
    
    try:
        response = requests.post(
            f"{API_BASE}/webhook/test",
            json=payload,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('success'):
                print(f"✓ Webhook test passed")
                print(f"  Result: {data.get('result', {}).get('status')}")
                return data
            else:
                print(f"✗ Webhook test failed: {data.get('error')}")
                return None
        else:
            print(f"✗ Webhook test failed: {response.status_code}")
            return None
    except Exception as e:
        print(f"✗ Webhook test error: {e}")
        return None

def main():
    """Main test function"""
    print("AI Sales Support API Test")
    print("=" * 40)
    
    # Test health check first
    if not test_health_check():
        print("\n⚠️  Health check failed. Make sure Odoo is running and the module is installed.")
        return
    
    # Test creating a sales request
    request_id = test_create_sales_request()
    
    if request_id:
        # Wait a bit for processing
        print("\nWaiting 2 seconds for processing...")
        time.sleep(2)
        
        # Test getting status
        test_get_request_status(request_id)
    
    # Test listing requests
    test_list_requests()
    
    # Test webhook simulation
    test_webhook_simulation()
    
    print("\n" + "=" * 40)
    print("API test completed!")

if __name__ == "__main__":
    main()