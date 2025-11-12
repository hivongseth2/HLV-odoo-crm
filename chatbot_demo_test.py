#!/usr/bin/env python3
"""
Demo script to test the AI Chatbot functionality
"""

import requests
import json
import sys

# Configuration
ODOO_URL = "http://localhost:8069"  # Change this to your Odoo URL
CHATBOT_MESSAGE_URL = f"{ODOO_URL}/chatbot/message"
CHATBOT_STATUS_URL = f"{ODOO_URL}/chatbot/status"

def test_chatbot_status():
    """Test chatbot status endpoint"""
    print("🔍 Testing chatbot status...")
    try:
        response = requests.get(CHATBOT_STATUS_URL, headers={'Content-Type': 'application/json'})
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Chatbot Status: {data}")
            return data.get('enabled', False) and data.get('configured', False)
        else:
            print(f"❌ Status check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error checking status: {e}")
        return False

def test_chatbot_message(message):
    """Test chatbot message endpoint"""
    print(f"💬 Testing message: '{message}'")
    try:
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "message": message
            },
            "id": 1
        }
        
        response = requests.post(
            CHATBOT_MESSAGE_URL, 
            json=payload,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'result' in data:
                result = data['result']
                if result.get('success'):
                    print(f"✅ AI Response: {result['response']}")
                    if result.get('inventory_results'):
                        print(f"📦 Found {len(result['inventory_results'])} products in inventory")
                    if result.get('web_results'):
                        print(f"🌐 Found {len(result['web_results'])} web results")
                    return True
                else:
                    print(f"❌ Chatbot error: {result.get('error', 'Unknown error')}")
                    return False
            else:
                print(f"❌ Unexpected response format: {data}")
                return False
        else:
            print(f"❌ Request failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error sending message: {e}")
        return False

def main():
    """Main test function"""
    print("🤖 AI Chatbot Demo Test")
    print("=" * 50)
    
    # Test status first
    if not test_chatbot_status():
        print("❌ Chatbot is not available or not configured properly")
        print("\n📝 To configure the chatbot:")
        print("1. Go to Settings > Website > Public Inventory")
        print("2. Enable 'AI Chatbot'")
        print("3. Enter your OpenAI API Key")
        print("4. Test the connection")
        sys.exit(1)
    
    print("\n✅ Chatbot is available and configured!")
    print("\n🧪 Running test messages...")
    print("-" * 30)
    
    # Test messages
    test_messages = [
        "Xin chào",
        "Tôi muốn tìm laptop",
        "Có điện thoại iPhone không?",
        "Giá máy tính bao nhiêu?",
        "Tồn kho sản phẩm ABC123",
        "Tìm sản phẩm không có trong kho"
    ]
    
    success_count = 0
    for i, message in enumerate(test_messages, 1):
        print(f"\n{i}. ", end="")
        if test_chatbot_message(message):
            success_count += 1
        print("-" * 30)
    
    print(f"\n📊 Test Results: {success_count}/{len(test_messages)} successful")
    
    if success_count == len(test_messages):
        print("🎉 All tests passed! Chatbot is working correctly.")
    else:
        print("⚠️ Some tests failed. Please check the configuration and logs.")

if __name__ == "__main__":
    main()