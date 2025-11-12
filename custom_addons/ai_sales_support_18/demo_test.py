#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Sales Support Module Demo Test Script
========================================

This script demonstrates the AI Sales Support module functionality.
Run this script to test the module without needing a full Odoo installation.
"""

import json
import requests
from datetime import datetime


class AISalesSupportDemo:
    def __init__(self, base_url="http://localhost:8069"):
        self.base_url = base_url
        self.session = requests.Session()
        
    def test_ai_status(self):
        """Test AI Sales Support status endpoint"""
        print("🔍 Testing AI Sales Support Status...")
        
        try:
            response = self.session.post(
                f"{self.base_url}/ai_sales/status",
                json={
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {}
                },
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('result', {}).get('enabled'):
                    print("✅ AI Sales Support is enabled and ready")
                    return True
                else:
                    print("❌ AI Sales Support is disabled")
                    return False
            else:
                print(f"❌ Status check failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Error checking status: {e}")
            return False
    
    def test_inquiry_processing(self):
        """Test inquiry processing endpoint"""
        print("\n🤖 Testing AI Inquiry Processing...")
        
        test_inquiry = """
        Tôi cần báo giá cho khách hàng:
        - Laptop Dell XPS 13: 3 chiếc
        - Mouse Logitech MX Master 3: 5 chiếc  
        - Bàn phím cơ Keychron K2: 2 chiếc
        - Màn hình Dell 24 inch: 3 chiếc
        
        Khách hàng cần giao hàng trong tuần này.
        """
        
        try:
            response = self.session.post(
                f"{self.base_url}/ai_sales/inquiry",
                json={
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {
                        "inquiry_text": test_inquiry,
                        "customer_id": None
                    }
                },
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('result', {}).get('success'):
                    print("✅ Inquiry processed successfully")
                    print(f"📋 Inquiry ID: {result['result'].get('inquiry_id')}")
                    print(f"🤖 AI Response: {result['result'].get('response')[:100]}...")
                    return result['result'].get('inquiry_id')
                else:
                    print(f"❌ Inquiry processing failed: {result.get('result', {}).get('message')}")
                    return None
            else:
                print(f"❌ Request failed: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ Error processing inquiry: {e}")
            return None
    
    def test_inquiry_status(self, inquiry_id):
        """Test inquiry status checking"""
        if not inquiry_id:
            return
            
        print(f"\n📊 Checking status for inquiry {inquiry_id}...")
        
        try:
            response = self.session.post(
                f"{self.base_url}/ai_sales/inquiry_status",
                json={
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {
                        "inquiry_id": inquiry_id
                    }
                },
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('result', {}).get('success'):
                    status = result['result']
                    print(f"✅ Status: {status.get('state')}")
                    print(f"💰 Total Amount: {status.get('total_amount', 'N/A')}")
                    print(f"⏱️ Processing Time: {status.get('processing_duration', 0)} minutes")
                    print(f"📦 Inventory Sufficient: {status.get('inventory_sufficient', 'Unknown')}")
                else:
                    print(f"❌ Status check failed: {result.get('result', {}).get('message')}")
            else:
                print(f"❌ Request failed: {response.status_code}")
                
        except Exception as e:
            print(f"❌ Error checking status: {e}")
    
    def test_quotation_creation(self, inquiry_id):
        """Test quotation creation"""
        if not inquiry_id:
            return
            
        print(f"\n📄 Testing quotation creation for inquiry {inquiry_id}...")
        
        try:
            response = self.session.post(
                f"{self.base_url}/ai_sales/create_quotation",
                json={
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {
                        "inquiry_id": inquiry_id,
                        "customer_id": 1  # Assuming customer ID 1 exists
                    }
                },
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('result', {}).get('success'):
                    print("✅ Quotation created successfully")
                    print(f"📄 Quotation ID: {result['result'].get('quotation_id')}")
                    print(f"📋 Quotation Name: {result['result'].get('quotation_name')}")
                else:
                    print(f"❌ Quotation creation failed: {result.get('result', {}).get('error')}")
            else:
                print(f"❌ Request failed: {response.status_code}")
                
        except Exception as e:
            print(f"❌ Error creating quotation: {e}")
    
    def run_full_demo(self):
        """Run complete demo test"""
        print("🚀 AI Sales Support Module Demo")
        print("=" * 50)
        print(f"🌐 Testing against: {self.base_url}")
        print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # Test 1: Check AI status
        if not self.test_ai_status():
            print("\n❌ AI Sales Support is not available. Please check configuration.")
            return
        
        # Test 2: Process inquiry
        inquiry_id = self.test_inquiry_processing()
        
        # Test 3: Check inquiry status
        self.test_inquiry_status(inquiry_id)
        
        # Test 4: Create quotation
        self.test_quotation_creation(inquiry_id)
        
        print("\n" + "=" * 50)
        print("✅ Demo completed!")
        print("\n📝 Next Steps:")
        print("1. Check the Odoo backend for created inquiries")
        print("2. Configure ChatGPT API key in Settings")
        print("3. Set up Zalo OA credentials")
        print("4. Add supplier contacts with Zalo user IDs")


def main():
    """Main demo function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='AI Sales Support Demo')
    parser.add_argument('--url', default='http://localhost:8069', 
                       help='Odoo server URL (default: http://localhost:8069)')
    
    args = parser.parse_args()
    
    demo = AISalesSupportDemo(args.url)
    demo.run_full_demo()


if __name__ == "__main__":
    main()