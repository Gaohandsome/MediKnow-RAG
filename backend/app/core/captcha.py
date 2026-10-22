"""图形验证码：生成图片 + 内存校验（带过期时间）。"""
from __future__ import annotations

import base64
import io
import random
import threading
import time
import uuid
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.core.config import settings

# 去掉易混淆字符 0/O/1/I/l
_CHARS = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_WIDTH, _HEIGHT = 132, 44


@dataclass
class _CaptchaItem:
    code: str
    expire_at: float


class CaptchaStore:
    """进程内验证码存储。校验成功后立即失效，防止重复使用。"""

    def __init__(self) -> None:
        self._data: dict[str, _CaptchaItem] = {}
        self._lock = threading.Lock()

    def put(self, code: str) -> str:
        captcha_id = uuid.uuid4().hex
        with self._lock:
            self._cleanup()
            self._data[captcha_id] = _CaptchaItem(
                code=code.upper(), expire_at=time.time() + settings.captcha_expire_seconds
            )
        return captcha_id

    def verify(self, captcha_id: str, code: str) -> bool:
        if not captcha_id or not code:
            return False
        with self._lock:
            item = self._data.pop(captcha_id, None)
        if item is None:
            return False
        if item.expire_at < time.time():
            return False
        return item.code == code.strip().upper()

    def _cleanup(self) -> None:
        now = time.time()
        expired = [key for key, item in self._data.items() if item.expire_at < now]
        for key in expired:
            self._data.pop(key, None)


captcha_store = CaptchaStore()


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _random_color(low: int, high: int) -> tuple[int, int, int]:
    return (random.randint(low, high), random.randint(low, high), random.randint(low, high))


def generate_captcha_image(code: str) -> str:
    """渲染验证码图片，返回 data URL 形式的 base64 PNG。"""
    image = Image.new("RGB", (_WIDTH, _HEIGHT), (247, 249, 253))
    draw = ImageDraw.Draw(image)

    # 背景干扰线
    for _ in range(6):
        draw.line(
            [
                (random.randint(0, _WIDTH), random.randint(0, _HEIGHT)),
                (random.randint(0, _WIDTH), random.randint(0, _HEIGHT)),
            ],
            fill=_random_color(180, 225),
            width=1,
        )
    # 背景噪点
    for _ in range(120):
        draw.point((random.randint(0, _WIDTH), random.randint(0, _HEIGHT)), fill=_random_color(170, 230))

    font = _load_font(28)
    step = _WIDTH // (len(code) + 1)
    for index, char in enumerate(code):
        color = _random_color(40, 120)
        char_image = Image.new("RGBA", (40, 40), (255, 255, 255, 0))
        char_draw = ImageDraw.Draw(char_image)
        char_draw.text((4, 0), char, font=font, fill=color)
        char_image = char_image.rotate(random.randint(-24, 24), resample=Image.BICUBIC, expand=False)
        image.paste(char_image, (step * (index + 1) - 26, random.randint(3, 8)), char_image)

    image = image.filter(ImageFilter.SMOOTH)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def new_captcha() -> tuple[str, str]:
    """生成一组验证码，返回 (captcha_id, 图片 data URL)。"""
    code = "".join(random.choice(_CHARS) for _ in range(settings.captcha_length))
    captcha_id = captcha_store.put(code)
    if settings.debug:
        # 仅在调试模式下输出，方便本地联调与自动化测试；生产环境请关闭 DEBUG
        from loguru import logger

        logger.info(f"[调试] 验证码 {captcha_id[:8]} 为 {code}")
    return captcha_id, generate_captcha_image(code)
