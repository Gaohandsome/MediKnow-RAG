"""媒体资源存储：解析阶段裁出的图片落盘/上云，并为图文问答提供 base64。

两种后端：
- local：写到 data/media/{doc_id}/xxx.png，由后端 `/api/v1/media` 静态目录对外提供 URL；
- qiniu：上传到七牛云对象存储，返回外链 URL（无需装 SDK，直接按官方签名规则调 HTTP 接口）。

对上层统一暴露 `save_image()` / `to_data_url()` / `resolve_url()` / `extract_image_urls()`。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import httpx
from loguru import logger
from PIL import Image

from app.core.config import settings

_IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

# 七牛上传入口，按区域依次尝试（深圳为 z2）
_QINIU_HOSTS = ("https://upload-z2.qiniup.com", "https://upload.qiniup.com", "https://up-z2.qiniup.com")


def _qiniu_token(key: str, expires: int = 3600) -> str:
    """按七牛规范生成上传凭证：ak:sign:encodedPolicy。"""
    policy = {
        "scope": f"{settings.qiniu_bucket}:{key}",
        "deadline": int(time.time()) + expires,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(policy, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    sign = hmac.new(
        settings.qiniu_secret_key.encode("utf-8"), encoded.encode("utf-8"), hashlib.sha1
    ).digest()
    return f"{settings.qiniu_access_key}:{base64.urlsafe_b64encode(sign).decode('ascii')}:{encoded}"


def _upload_qiniu(key: str, data: bytes, content_type: str) -> bool:
    """上传到七牛；成功返回 True（不抛异常，失败时调用方回退本地）。"""
    if not (settings.qiniu_access_key and settings.qiniu_secret_key and settings.qiniu_bucket):
        logger.warning("七牛未配置 AK/SK/Bucket，回退为本地存储")
        return False
    token = _qiniu_token(key)
    for host in _QINIU_HOSTS:
        try:
            response = httpx.post(
                host,
                data={"token": token, "key": key},
                files={"file": (Path(key).name, data, content_type)},
                timeout=30,
            )
            if response.status_code == 200:
                logger.info(f"图片已上传七牛：{key}")
                return True
            logger.warning(f"七牛上传失败 {host}：{response.status_code} {response.text[:200]}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"七牛上传异常 {host}：{exc}")
    return False


def object_key(ref: str) -> str | None:
    """从任意形式的 URL / 对象键里取出对象键（去掉协议、域名、查询串）。"""
    text = (ref or "").strip()
    if not text:
        return None
    if "://" in text:
        rest = text.split("://", 1)[1]
        text = rest.split("/", 1)[1] if "/" in rest else ""
    text = text.split("?", 1)[0].split("#", 1)[0].lstrip("/")
    return text or None


def _sign_cdn(base: str, key: str, expires: int) -> str:
    """七牛私有空间下载签名（CDN 域名下的 token 规则）。"""
    deadline = int(time.time()) + max(60, expires)
    path = "/" + key.lstrip("/")
    digest = hmac.new(
        settings.qiniu_secret_key.encode("utf-8"),
        f"{path}?e={deadline}".encode("utf-8"),
        hashlib.sha1,
    ).digest()
    token = f"{settings.qiniu_access_key}:{base64.urlsafe_b64encode(digest).decode('ascii')}"
    return f"{base}{path}?e={deadline}&token={token}"


def _presign_s3(host: str, key: str, expires: int) -> str:
    """按 AWS SigV4 规则给 S3 兼容端点生成预签名 GET URL。"""
    region = settings.qiniu_s3_region or "cn-south-1"
    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    canonical_uri = "/" + urllib.parse.quote(key.lstrip("/"), safe="/")
    query = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{settings.qiniu_access_key}/{date_stamp}/{region}/s3/aws4_request",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(max(60, min(expires, 604800))),
        "X-Amz-SignedHeaders": "host",
    }
    canonical_query = "&".join(
        f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in sorted(query.items())
    )
    canonical_request = (
        f"GET\n{canonical_uri}\n{canonical_query}\nhost:{host}\n\nhost\nUNSIGNED-PAYLOAD"
    )
    string_to_sign = (
        "AWS4-HMAC-SHA256\n"
        f"{amz_date}\n{date_stamp}/{region}/s3/aws4_request\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )
    signing_key = f"AWS4{settings.qiniu_secret_key}".encode("utf-8")
    for part in (date_stamp, region, "s3", "aws4_request"):
        signing_key = hmac.new(signing_key, part.encode("utf-8"), hashlib.sha256).digest()
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"https://{host}{canonical_uri}?{canonical_query}&X-Amz-Signature={signature}"


def resolve_url(ref: str) -> str:
    """把库里存的规范 URL 转成"此刻可访问"的 URL。

    - local 模式：原样返回；
    - qiniu + 已绑定 CDN 域名：public 直连 / signed 追加 `?e=&token=`；
    - qiniu + 未绑定域名：走 S3 端点，私有空间必须签名。
    签名在每次输出时现算，所以库里的 URL 永远不会过期。
    """
    if not ref:
        return ""
    if settings.media_storage != "qiniu":
        return ref

    key = object_key(ref)
    if not key:
        return ref

    if settings.qiniu_domain:
        base = f"https://{settings.qiniu_domain}".rstrip("/")
        if settings.media_url_mode == "signed":
            return _sign_cdn(base, key, settings.media_sign_expire)
        return f"{base}/{key}"

    host = settings.qiniu_object_host
    if not host:
        return ref
    # S3 端点对私有桶禁止匿名访问，签名是唯一可行的读法
    return _presign_s3(host, key, settings.media_sign_expire)


def strip_sign(ref: str) -> str:
    """去掉查询串，只留规范 URL（入库/存历史用，避免把签名写死）。"""
    text = (ref or "").strip()
    if not text:
        return ""
    return text.split("?", 1)[0].split("#", 1)[0]


def refresh_url(ref: str) -> str:
    """读历史数据时用：给对象存储的图重新签一次名，让旧消息里的缩略图不过期。

    与 `resolve_url` 的区别是它会先剥掉可能已存在的旧签名，
    并且跳过本地回退地址（那些地址本来就不需要签名）。
    """
    if not ref:
        return ""
    if ref.startswith("http://127.0.0.1") or ref.startswith("http://localhost"):
        return ref
    return resolve_url(strip_sign(ref))


def _normalize(image: Image.Image) -> Image.Image:
    """统一为 RGB，并把长边压到配置上限，控制 base64 体积与 token 消耗。"""
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    limit = max(320, settings.vision_image_max_side)
    if max(image.size) > limit:
        ratio = limit / max(image.size)
        image = image.resize(
            (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
            Image.LANCZOS,
        )
    return image


def save_image(image: Image.Image, key: str) -> str:
    """保存裁图，返回可直接放进提示词的 URL。

    key 形如 `{doc_id}/p4_fig1.png`；qiniu 模式下 key 即对象键。
    """
    image = _normalize(image)
    buffer = io.BytesIO()
    # PNG 对流程图/表格线条更清晰；体积由长边上限控制
    image.save(buffer, format="PNG", optimize=True)
    data = buffer.getvalue()

    if settings.media_storage == "qiniu" and _upload_qiniu(key, data, "image/png"):
        # 只存规范 URL（域名 + 对象键），签名留给输出时现算
        return f"{settings.media_url}/{key}"

    target = settings.media_path / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    if settings.media_storage == "qiniu":
        # 上传失败回退本地，URL 指向后端静态目录，而不是七牛域名
        return f"http://127.0.0.1:8001{settings.media_url_prefix}/{key}"
    return f"{settings.media_url}/{key}"


def image_data_url(image: Image.Image) -> str:
    """把内存里的图像直接转成 data URL（解析阶段喂给多模态模型，省一次外链往返）。"""
    image = _normalize(image)
    if image.mode == "L":
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def local_path_of(url: str) -> Path | None:
    """把媒体 URL 还原成本地路径（仅本地存储模式有效）。"""
    if settings.media_storage != "local":
        # 七牛模式下 URL 前缀可能是 CDN 域名，绝不能当成本地路径
        return None
    prefix = settings.media_url
    if not url.startswith(prefix):
        return None
    relative = url[len(prefix):].lstrip("/")
    if not relative or ".." in relative:
        return None
    return settings.media_path / relative


def to_data_url(url: str) -> str | None:
    """下载/读取图片并转成 base64 data URL，供多模态模型使用。

    本地媒体直接读文件；七牛等外链走 HTTP 下载。失败返回 None（不影响纯文本回答）。
    """
    try:
        url = resolve_url(url)
        suffix = Path(url.split("?")[0]).suffix.lower() or ".png"
        media_type = _IMAGE_MEDIA_TYPES.get(suffix, "image/png")

        local = local_path_of(url)
        if local is None and settings.media_storage == "qiniu":
            # 上传七牛失败的图仍会落盘，优先读本地副本，省一次网络往返
            key = object_key(url)
            candidate = settings.media_path / key if key else None
            if candidate is not None and candidate.exists():
                local = candidate
        if local is not None:
            if not local.exists():
                logger.warning(f"本地图片不存在：{local}")
                return None
            raw = local.read_bytes()
        else:
            response = httpx.get(url, timeout=settings.vision_timeout, follow_redirects=True)
            response.raise_for_status()
            raw = response.content
            media_type = response.headers.get("content-type", media_type).split(";")[0]

        # 统一再压一次，避免外链原图过大
        image = Image.open(io.BytesIO(raw))
        image = _normalize(image)
        buffer = io.BytesIO()
        if image.mode == "L":
            image = image.convert("RGB")
        image.save(buffer, format="JPEG", quality=85, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"图片转 base64 失败：{url} - {exc}")
        return None


def image_id_of(url: str) -> str:
    """图片稳定标识（用于去重）。"""
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
