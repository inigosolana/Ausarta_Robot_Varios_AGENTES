import os
from dotenv import load_dotenv
from livekit import api

load_dotenv()

LIVEKIT_URL = os.getenv('LIVEKIT_URL')
LIVEKIT_API_KEY = os.getenv('LIVEKIT_API_KEY')
LIVEKIT_API_SECRET = os.getenv('LIVEKIT_API_SECRET')

class LazyLiveKitAPI:
    def __init__(self, url, api_key, api_secret):
        self._url = url
        self._api_key = api_key
        self._api_secret = api_secret
        self._instance = None

    def _get_instance(self):
        if self._instance is None:
            if self._url and self._api_key and self._api_secret:
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                self._instance = api.LiveKitAPI(self._url, self._api_key, self._api_secret)
            else:
                print("⚠️ WARNING: LiveKit credentials missing.")
                self._instance = None
        return self._instance

    def __getattr__(self, item):
        inst = self._get_instance()
        if inst is None:
            raise AttributeError(f"LiveKitAPI not initialized (missing config), cannot get '{item}'")
        return getattr(inst, item)

lkapi = LazyLiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
