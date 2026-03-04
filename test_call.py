import requests
import json

url = "http://localhost:8003/api/calls/outbound"
payload = {
    "phoneNumber": "+34621151394",
    "agentId": 2,
    "leadId": 1,
    "customerName": "inigo test"
}

try:
    response = requests.post(url, json=payload)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")
