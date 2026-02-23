import asyncio
from livekit import api
from dotenv import load_dotenv
import os

load_dotenv()
async def main():
    lkapi = api.LiveKitAPI(os.getenv('LIVEKIT_URL'), os.getenv('LIVEKIT_API_KEY'), os.getenv('LIVEKIT_API_SECRET'))
    
    room_name = 'test_room'
    trunk_id = os.getenv('SIP_OUTBOUND_TRUNK_ID')
    phone = '+34655216465'
    
    print(f'Using LK URL: {os.getenv("LIVEKIT_URL")}')
    print(f'Using Trunk: {trunk_id}')
    
    try:
        await lkapi.room.create_room(api.CreateRoomRequest(name=room_name))
    except Exception as e:
        print(f'Warn: {e}')
        
    try:
        req = api.CreateSIPParticipantRequest(
            sip_trunk_id=trunk_id,
            sip_call_to=phone,
            room_name=room_name,
            participant_identity='test_id_123',
            participant_name='Test User'
        )
        print('Creating SIP participant...', req)
        res = await lkapi.sip.create_sip_participant(req)
        print('SUCCESS:', res)
    except Exception as e:
        print(f'Error creating SIP participant: {e}')
        
    await lkapi.aclose()

asyncio.run(main())
