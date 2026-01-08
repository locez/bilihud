# -*- coding: utf-8 -*-
import asyncio
import http.cookies
from typing import Optional, Callable
import aiohttp
import blivedm
import blivedm.models.web as web_models


class DanmakuClient:
    """
    弹幕客户端，用于获取B站直播弹幕
    """

    def __init__(self, room_id: int, sessdata: str = ''):
        self.room_id = room_id
        self.sessdata = sessdata
        self.session: Optional[aiohttp.ClientSession] = None
        self.client: Optional[blivedm.BLiveClient] = None
        self.handler: Optional[DanmakuHandler] = None
        self.on_danmaku_received: Optional[Callable[[web_models.DanmakuMessage], None]] = None
        self.on_gift_received: Optional[Callable[[web_models.GiftMessage], None]] = None
        self.on_interact_received: Optional[Callable[[web_models.InteractWordV2Message], None]] = None
        self.on_login_failed: Optional[Callable[[str], None]] = None # callback(message)

    def set_danmaku_callback(self, callback: Callable[[web_models.DanmakuMessage], None]):
        """设置弹幕接收回调函数"""
        self.on_danmaku_received = callback

    def set_gift_callback(self, callback: Callable[[web_models.GiftMessage], None]):
        """设置礼物接收回调函数"""
        self.on_gift_received = callback

    def set_interact_callback(self, callback: Callable[[web_models.InteractWordV2Message], None]):
        """设置互动接收回调函数 (进房/关注)"""
        self.on_interact_received = callback

    def set_login_failed_callback(self, callback: Callable[[str], None]):
        """设置登录失效回调"""
        self.on_login_failed = callback

    async def start(self):
        """在事件循环中启动弹幕客户端"""
        # 初始化session
        cookies = http.cookies.SimpleCookie()
        
        # 尝试优先从Keyring加载Cookies
        from .auth import AuthManager
        auth_manager = AuthManager()
        saved_cookies = auth_manager.load_cookies()
        
        loaded_from_keyring = False
        if saved_cookies:
            # 验证Cookie有效性
            is_valid = await auth_manager.validate_session(saved_cookies)
            if is_valid:
                for k, v in saved_cookies.items():
                    cookies[k] = v
                print("Successfully loaded validated cookies from Keyring")
                loaded_from_keyring = True
            else:
                print("Keyring cookies expired")
                if self.on_login_failed:
                    self.on_login_failed("本地保存的登录信息已失效，请重新登录")

        # 如果没有有效的Keyring Cookies，尝试从浏览器加载
        if not loaded_from_keyring:
            browser_cookies = load_bilibili_cookies()
            if browser_cookies:
                # print("Successfully loaded cookies from browser")
                # 将http.cookiejar.CookieJar转换为SimpleCookie或简单dict
                for cookie in browser_cookies:
                    cookies[cookie.name] = cookie.value
        
        if self.sessdata:
            cookies['SESSDATA'] = self.sessdata
            
        # 确保domain设置正确
        if 'SESSDATA' in cookies:
            cookies['SESSDATA']['domain'] = 'bilibili.com'

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0'
        }
        self.session = aiohttp.ClientSession(headers=headers)
        self.session.cookie_jar.update_cookies(cookies)

        # 创建客户端和处理器
        self.client = blivedm.BLiveClient(self.room_id, session=self.session)
        self.handler = DanmakuHandler()
        self.handler.set_danmaku_client(self)
        self.client.set_handler(self.handler)

        loop = asyncio.get_event_loop()
        loop.call_soon(self.client.start)
        # 启动客户端
        # self.client.start()
        # await asyncio.sleep(0.1)  # 让出控制权以启动客户端

    async def send_danmaku(self, message: str) -> tuple[bool, str]:
        """发送弹幕"""
        if not self.session or not message:
            return False, "会话未初始化或消息为空"
            
        url = 'https://api.live.bilibili.com/msg/send'
        
        # 从cookie中获取csrf token (bili_jct)
        csrf_token = ''
        for cookie in self.session.cookie_jar:
            if cookie.key == 'bili_jct':
                csrf_token = cookie.value
                break
                
        if not csrf_token:
            # print("Error: No csrf_token found in cookies")
            return False, "未找到CSRF Token，请重新连接或检查Cookie"
            
        data = {
            'bubble': '0',
            'msg': message,
            'color': '16777215',
            'mode': '1',
            'fontsize': '25',
            'rnd': str(int(asyncio.get_event_loop().time())),
            'roomid': self.room_id,
            'csrf': csrf_token,
            'csrf_token': csrf_token,
        }
        
        try:
            async with self.session.post(url, data=data) as res:
                if res.status != 200:
                    print(f"Send danmaku HTTP error: {res.status}")
                    return False, f"HTTP错误: {res.status}"
                json_data = await res.json()
                if json_data['code'] == 0:
                    return True, "发送成功"
                else:
                    print(f"Send danmaku failed: {json_data['message']}")
                    return False, f"发送失败: {json_data['message']}"
        except Exception as e:
            print(f"Send danmaku exception: {e}")
            return False, f"发送异常: {str(e)}"

    async def stop(self):
        """停止弹幕客户端"""
        if self.client:
            await self.client.stop_and_close()
        if self.session:
            await self.session.close()


class DanmakuHandler(blivedm.BaseHandler):
    """弹幕处理器"""

    def __init__(self):
        super().__init__()
        self.danmaku_client: Optional[DanmakuClient] = None

    def set_danmaku_client(self, client: DanmakuClient):
        self.danmaku_client = client

    def _on_danmaku(self, client: blivedm.BLiveClient, message: web_models.DanmakuMessage):
        """处理弹幕消息"""
        if self.danmaku_client and self.danmaku_client.on_danmaku_received:
            self.danmaku_client.on_danmaku_received(message)

    def _on_gift(self, client: blivedm.BLiveClient, message: web_models.GiftMessage):
        """处理礼物消息"""
        if self.danmaku_client and self.danmaku_client.on_gift_received:
            self.danmaku_client.on_gift_received(message)
            
    def _on_interact_word_v2(self, client: blivedm.BLiveClient, message: web_models.InteractWordV2Message):
        """处理进入房间/关注"""
        if self.danmaku_client and self.danmaku_client.on_interact_received:
            self.danmaku_client.on_interact_received(message)

    def _on_super_chat(self, client: blivedm.BLiveClient, message: web_models.SuperChatMessage):
        """处理醒目留言"""
        # 可以在这里处理醒目留言
        pass


def load_bilibili_cookies():
    """尝试从浏览器加载B站Cookies"""
    try:
        import browser_cookie3
        # 尝试从Chrome加载
        # print("Attempting to load cookies from Chrome...")
        cj = browser_cookie3.chrome(domain_name='.bilibili.com')
        return cj
    except Exception as e:
        print(f"Chrome cookies failed: {e}")
        try:
            import browser_cookie3
            # 尝试从Edge加载
            cj = browser_cookie3.edge(domain_name='.bilibili.com')
            return cj
        except Exception as e:
            print(f"Edge cookies failed: {e}")
            try:
                import browser_cookie3
                # 尝试从Firefox加载
                cj = browser_cookie3.firefox(domain_name='.bilibili.com')
                return cj
            except Exception as e:
                print(f"Firefox cookies failed: {e}")
                return None



