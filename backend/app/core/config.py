"""应用配置：统一从 .env 读取，禁止在业务代码里硬编码敏感信息。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """全局配置对象（单例）。"""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 应用
    app_name: str = "MediKnow-RAG · 院内知识库问答"
    app_env: str = "dev"
    debug: bool = True
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    log_dir: str = "logs"

    # MySQL
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "mediknow"
    mysql_charset: str = "utf8mb4"

    # Milvus
    milvus_uri: str = "http://127.0.0.1:19530"
    milvus_token: str = ""
    milvus_database: str = "default"
    milvus_collection_prefix: str = "kb_"

    # 向量模型
    embedding_model_path: str = ""
    embedding_device: str = "cpu"
    embedding_batch_size: int = 4
    embedding_max_length: int = 1024
    embedding_dim: int = 1024

    # 重排模型
    rerank_model_path: str = ""
    rerank_enabled: bool = True
    rerank_top_n: int = 5

    # 大模型
    llm_api_key: str = ""
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_default_model: str = "qwen-max"
    llm_available_models: str = "qwen-max"
    llm_timeout: int = 120
    llm_temperature: float = 0.7
    llm_top_p: float = 0.8
    llm_max_tokens: int = 2048
    llm_history_rounds: int = 5
    # 深度思考：qwen3 系列默认开，回答前先写一大段推理，首字延迟和总耗时都翻几倍。
    # 本项目的答案基本是「照资料归纳」，关掉后质量几乎无损、响应明显变快。
    llm_enable_thinking: bool = False

    # 限流保护：每分钟最多发多少个请求（0=不限制）。阿里云按模型算 RPM，
    # 超了就是 429 limit_requests，并发打满时只会整批失败，不如自己排队。
    llm_max_rpm: int = 60
    # 撞到 429 时的最大尝试次数（含首次），退避 1/2/4/8…秒
    llm_rate_retries: int = 5
    vision_model: str = "qwen-vl-ocr"

    # 多模态问答（图文混合检索）
    vision_enabled: bool = True
    llm_vl_model: str = "qwen-vl-max"
    vision_max_images: int = 3
    vision_image_max_side: int = 1280
    vision_timeout: int = 60

    # 图片/媒体存储：local=后端静态目录，qiniu=七牛云对象存储
    media_storage: str = "local"
    media_dir: str = "data/media"
    media_base_url: str = ""
    media_public_base: str = ""
    media_crop_resolution: int = 200
    qiniu_access_key: str = ""
    qiniu_secret_key: str = ""
    qiniu_bucket: str = ""
    qiniu_domain: str = ""
    # 私有空间签名：URL 不落库，每次输出时现签，避免过期后图片全挂
    media_url_mode: str = "signed"
    media_sign_expire: int = 86400
    # 未绑定 CDN 域名时，直连七牛 S3 兼容端点（形如 {bucket}.s3.cn-south-1.qiniucs.com）
    qiniu_s3_region: str = "cn-south-1"
    qiniu_s3_host: str = ""

    # 检索
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 100
    rag_top_k: int = 5
    rag_candidate_k: int = 20
    rag_score_threshold: float = 0.0
    # 多路召回的 RRF 融合常数（越小越偏向高排名）
    rag_rrf_k: int = 60

    # 知识库共享：院内资料本应全院可用。
    # 开启后所有登录用户都能「看到并使用」任意知识库（列库、看文档、检索问答），
    # 但创建 / 改名 / 删除 / 上传 / 重解析仍然只允许所有者操作。
    # 需要人人各管各的私有库时，把它设为 false 即可恢复按 user_id 隔离。
    kb_shared_read: bool = True

    # 查询理解：意图识别 + 策略选择 + 改写（假设答案/子查询/简化/回溯）
    query_rewrite_enabled: bool = True
    query_rewrite_min_chars: int = 12
    query_rewrite_timeout: int = 30
    query_rewrite_cache_ttl: int = 3600
    query_max_variants: int = 4

    # 精确问答缓存：Redis 一级 + MySQL 持久化，BM25 命中直接回答案
    qa_cache_enabled: bool = True
    qa_cache_threshold: float = 0.8
    qa_cache_ttl: int = 86400
    qa_cache_min_answer_chars: int = 30
    # 只留「高频」问答对：MySQL 超过这个条数就按 hit_count 从低到高淘汰
    qa_cache_max_pairs: int = 300
    # 命中计数先攒在 Redis，攒够这么多次再批量回写 MySQL（避免每次命中都写库）
    qa_hit_flush_every: int = 20

    # Redis（可选）：未安装或连不上时自动降级为进程内缓存
    redis_enabled: bool = False
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0
    # 留空则按 host/port/password/db 自动拼装；需要完整自定义时（如 sentinel、集群）再填
    redis_url: str = ""
    redis_timeout: float = 1.5

    @property
    def redis_dsn(self) -> str:
        """实际连接串：显式 redis_url 优先，否则由分散字段拼装。"""
        if self.redis_url:
            return self.redis_url
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # 医疗安全层
    medical_disclaimer_enabled: bool = True
    medical_disclaimer: str = (
        "以上内容依据院内知识库资料整理，仅供医疗专业人员参考，"
        "不能替代执业医师的诊断与处方。"
    )
    safety_red_flag_enabled: bool = True
    safety_refuse_when_no_context: bool = True
    # 最低稠密相关度（bge-m3 余弦相似度，0~1）；实测：无关提问 ≤0.40，相关提问 ≥0.61，故取 0.5
    safety_min_score: float = 0.5

    # 安全
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    captcha_length: int = 4
    captcha_expire_seconds: int = 180

    # 上传
    upload_dir: str = "data/uploads"
    max_upload_mb: int = 50

    @property
    def insecure_defaults(self) -> list[str]:
        """仍在使用示例值的敏感配置项，供启动自检。

        这些值写在开源代码里，任何人都能看到；忘记配置就等于用公开密钥签名
        token。开发环境只告警，其它环境直接拒绝启动。
        """
        placeholders = {"", "change-me", "please-change-me", "your-secret-key", "changeme"}
        issues = []
        if self.jwt_secret.strip().lower() in placeholders:
            issues.append("JWT_SECRET")
        if not self.llm_api_key.strip():
            issues.append("LLM_API_KEY")
        return issues

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            f"?charset={self.mysql_charset}"
        )

    @property
    def server_url(self) -> str:
        """不含库名的 MySQL 连接串，用于自动建库。"""
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/?charset={self.mysql_charset}"
        )

    @property
    def available_models(self) -> list[str]:
        return [m.strip() for m in self.llm_available_models.split(",") if m.strip()]

    @property
    def upload_path(self) -> Path:
        path = Path(self.upload_dir)
        if not path.is_absolute():
            path = BASE_DIR / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def log_path(self) -> Path:
        path = Path(self.log_dir)
        if not path.is_absolute():
            path = BASE_DIR / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def media_path(self) -> Path:
        """裁图等媒体资源落盘目录。"""
        path = Path(self.media_dir)
        if not path.is_absolute():
            path = BASE_DIR / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def media_url_prefix(self) -> str:
        """本地媒体访问路径（挂载在 main.py 上）。"""
        return f"{self.api_prefix}/media"

    @property
    def qiniu_object_host(self) -> str:
        """七牛 S3 兼容端点主机名（未绑定 CDN 域名时用它直连对象）。"""
        if self.qiniu_s3_host:
            return self.qiniu_s3_host.strip()
        if self.qiniu_bucket and self.qiniu_s3_region:
            return f"{self.qiniu_bucket}.s3.{self.qiniu_s3_region}.qiniucs.com"
        return ""

    @property
    def media_url(self) -> str:
        """裁图的对外 URL 前缀。配置了 MEDIA_BASE_URL 时优先使用。

        qiniu 模式优先用绑定的 CDN 域名；没有域名时退回 S3 直连端点，
        此时访问必须带签名（私有空间不支持匿名 GET）。
        """
        if self.media_base_url:
            return self.media_base_url.rstrip("/")
        if self.media_storage == "qiniu":
            if self.qiniu_domain:
                return f"https://{self.qiniu_domain}".rstrip("/")
            if self.qiniu_object_host:
                return f"https://{self.qiniu_object_host}"
        return f"http://127.0.0.1:8001{self.media_url_prefix}"

    @property
    def base_dir(self) -> Path:
        return BASE_DIR


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
