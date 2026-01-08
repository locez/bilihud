# -*- coding: utf-8 -*-
import asyncio
import aiohttp
import qrcode
import keyring
import json
import logging
import time
from typing import Optional, Dict, Tuple, Any
from io import BytesIO
from PIL import Image

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SERVICE_ID = "bilihud"
USERNAME_KEY = "bilibili_cookies"

class AuthManager:
    """
    Manage Bilibili Authentication via QR Code
    """
    
    BASE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
    POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def get_qrcode(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Get QR code URL and Key
        Returns: (url, qrcode_key)
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            try:
                async with session.get(self.BASE_URL) as response:
                    data = await response.json()
                    if data['code'] == 0:
                        return data['data']['url'], data['data']['qrcode_key']
                    else:
                        logger.error(f"Failed to get QR code: {data}")
                        return None, None
            except Exception as e:
                logger.error(f"Exception requesting QR code: {e}")
                return None, None

    def generate_qr_image(self, url: str) -> Optional[BytesIO]:
        """
        Generate QR code image from URL
        Returns: BytesIO object containing PNG image
        """
        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(url)
            qr.make(fit=True)

            img = qr.make_image(fill_color="black", back_color="white")
            bio = BytesIO()
            img.save(bio, format="PNG")
            bio.seek(0)
            return bio
        except Exception as e:
            logger.error(f"Failed to generate QR image: {e}")
            return None

    async def poll_status(self, qrcode_key: str) -> Tuple[int, str, Optional[Dict]]:
        """
        Poll login status
        Returns: (code, message, cookies_dict)
        code: 0=Success, 86101=Scanned, 86090=Not Scanned, 86038=Expired
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            try:
                params = {'qrcode_key': qrcode_key}
                async with session.get(self.POLL_URL, params=params) as response:
                    data = await response.json()
                    
                    if data['code'] == 0:
                        code = data['data']['code']
                        msg = data['data']['message']
                        
                        if code == 0:
                            # Login success, extract cookies
                            cookies = {}
                            for cookie in session.cookie_jar:
                                cookies[cookie.key] = cookie.value
                            
                            # Also check Set-Cookie headers directly if needed, usually cookie_jar has them
                            # Filter for essential cookies
                            essential_keys = ['SESSDATA', 'bili_jct', 'DedeUserID', 'DedeUserID__ckMd5']
                            filtered_cookies = {k: v for k, v in cookies.items() if k in essential_keys}
                            
                            return 0, "登录成功", filtered_cookies
                        
                        return code, msg, None
                    else:
                        return -1, f"API Error: {data['code']}", None
            except Exception as e:
                logger.error(f"Exception polling status: {e}")
                return -1, str(e), None

    def save_cookies(self, cookies: Dict[str, str]) -> bool:
        """
        Save cookies securely using keyring
        """
        try:
            cookie_json = json.dumps(cookies)
            keyring.set_password(SERVICE_ID, USERNAME_KEY, cookie_json)
            return True
        except Exception as e:
            logger.error(f"Failed to save cookies to keyring: {e}")
            return False

    def load_cookies(self) -> Optional[Dict[str, str]]:
        """
        Load cookies from keyring
        """
        try:
            cookie_json = keyring.get_password(SERVICE_ID, USERNAME_KEY)
            if cookie_json:
                return json.loads(cookie_json)
            return None
        except Exception as e:
            logger.error(f"Failed to load cookies from keyring: {e}")
            return None
            
    def clear_cookies(self):
        """Clear stored cookies"""
        try:
            keyring.delete_password(SERVICE_ID, USERNAME_KEY)
        except Exception as e:
            logger.error(f"Failed to delete cookies: {e}")

    async def validate_session(self, cookies: Dict[str, str]) -> bool:
        """
        Validate if the current cookies are logged in
        """
        url = "https://api.bilibili.com/x/web-interface/nav"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        try:
            async with aiohttp.ClientSession(cookies=cookies, headers=headers) as session:
                async with session.get(url) as resp:
                    data = await resp.json()
                    if data['code'] == 0:
                         return data['data'].get('isLogin', False)
                    return False
        except Exception as e:
            logger.error(f"Session validation failed: {e}")
            return False

