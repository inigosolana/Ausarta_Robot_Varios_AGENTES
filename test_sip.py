
import asyncio
import os
import time
from dotenv import load_dotenv
from livekit import api

load_dotenv()

async def test_sip():
    url = os.getenv("LIVEKIT_URL")
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")
    trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")
    phone = "+34655216465"
    
    print(f"Connecting to {url} with trunk {trunk_id}...")
    
    lkapi = api.LiveKitAPI(url, api_key, api_secret)
    
    room_name = f"test_sip_{int(time.time())}"
    
    try:
        await lkapi.room.create_room(api.CreateRoomRequest(name=room_name))
        print(f"Room {room_name} created.")
        
        print(f"Dialing {phone}...")
        res = await lkapi.sip.create_sip_participant(api.CreateSIPParticipantRequest(
            sip_trunk_id=trunk_id,
            sip_call_to=phone,
            room_name=room_name,
            participant_identity=f"user_{phone}_{int(time.time())}",
            participant_name="Test User"
        ))
        print("Success!", res)
    except Exception as e:
        print("Error:", e)
    finally:
        await lkapi.aclose()

if __name__ == "__main__":
    asyncio.run(test_sip())

