"""把已落盘的本地裁图上传到七牛，并改写库里的图片 URL 为规范 URL。

规范 URL = `{MEDIA_URL}/{对象键}`（不含签名）。私有空间在输出时会现签，
所以入库的 URL 永远不过期。支持重复执行（幂等）。

用法：
    python scripts/ops/migrate_media_to_qiniu.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR / "backend"))

import pymysql  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services import media  # noqa: E402

MEDIA_URL_PREFIX = settings.media_url_prefix.lstrip("/")  # api/v1/media


def key_of(url: str) -> str:
    """从历史 URL 里解析出对象键（兼容本地静态路径与已在七牛的地址）。"""
    text = (url or "").strip()
    if "://" in text:
        rest = text.split("://", 1)[1]
        text = rest.split("/", 1)[1] if "/" in rest else ""
    text = text.split("?", 1)[0].split("#", 1)[0].lstrip("/")
    for prefix in (MEDIA_URL_PREFIX + "/", "api/v1/media/", "media/"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if settings.media_storage != "qiniu":
        print(f"当前 MEDIA_STORAGE={settings.media_storage}，不是 qiniu，无需迁移")
        return 1

    print(f"目标桶：{settings.qiniu_bucket}  访问基址：{settings.media_url}")
    print(f"URL 模式：{settings.media_url_mode}  有效期：{settings.media_sign_expire}s")

    media_root = settings.media_path
    files = sorted(p for p in media_root.rglob("*") if p.is_file())
    print(f"本地裁图：{len(files)} 个")

    uploaded: dict[str, str] = {}
    for index, path in enumerate(files, start=1):
        key = path.relative_to(media_root).as_posix()
        canonical = f"{settings.media_url}/{key}"
        uploaded[key] = canonical
        if args.dry_run:
            print(f"  [{index}/{len(files)}] {key} -> {canonical}")
            continue
        ok = media._upload_qiniu(key, path.read_bytes(), "image/png")
        print(f"  [{index}/{len(files)}] {key} {'已上传' if ok else '上传失败'}")

    if args.dry_run:
        return 0

    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset="utf8mb4",
    )
    cur = conn.cursor()
    cur.execute("select id, image_urls, parent_content from document_chunks")
    rows = cur.fetchall()
    touched = 0
    for chunk_id, image_urls, parent_content in rows:
        new_images = image_urls or ""
        new_parent = parent_content or ""

        if image_urls:
            try:
                items = json.loads(image_urls)
            except json.JSONDecodeError:
                items = []
            changed = False
            for item in items:
                if not isinstance(item, dict):
                    continue
                old = item.get("url", "")
                key = key_of(old)
                canonical = uploaded.get(key) or f"{settings.media_url}/{key}"
                if old != canonical:
                    item["url"] = canonical
                    changed = True
            if changed:
                new_images = json.dumps(items, ensure_ascii=False)

        if parent_content:
            # 父块里的图片标记按顺序与 image_urls 一一对应，直接按序替换链接部分
            try:
                ordered = [item.get("url", "") for item in json.loads(new_images or "[]") if isinstance(item, dict)]
            except json.JSONDecodeError:
                ordered = []
            if ordered:
                cursor_index = {"i": 0}

                def _swap(match: re.Match) -> str:
                    pos = cursor_index["i"]
                    cursor_index["i"] = pos + 1
                    url = ordered[pos] if pos < len(ordered) else match.group(2)
                    return f"{match.group(1)}{url}]"

                new_parent = re.sub(
                    r"(\[关联图片[:：].*?/\s*图片链接[:：]\s*)(\S+?)\]",
                    _swap,
                    new_parent,
                )

        if new_images != (image_urls or "") or new_parent != (parent_content or ""):
            cur.execute(
                "update document_chunks set image_urls=%s, parent_content=%s where id=%s",
                (new_images, new_parent, chunk_id),
            )
            touched += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"已更新 {touched} 个块的图片地址")

    sample = next(iter(uploaded.values()), "")
    if sample:
        signed = media.resolve_url(sample)
        print(f"\n规范 URL：{sample}")
        print(f"签名 URL：{signed[:120]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
