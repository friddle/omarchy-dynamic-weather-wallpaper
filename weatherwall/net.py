"""统一 HTTP 出口：所有对外请求(探测/天气/生图)走这里，支持配置代理。

代理来源:
  1. 配置 network.proxy (优先, 如 http://10.10.32.8:7890)
  2. 未配置时沿用系统环境变量 (http_proxy / https_proxy / all_proxy)
"""

import json
import ssl
import time
import urllib.error
import urllib.request

UA = "weatherwall/0.1"


def cfg_proxy(cfg: dict | None) -> str:
    if not cfg:
        return ""
    return str((cfg.get("network") or {}).get("proxy") or "").strip()


def opener(proxy: str = "", direct: bool = False) -> urllib.request.OpenerDirector:
    if direct:
        # 强制直连: 忽略配置代理与系统/环境变量代理(IP 定位等场景)
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    # 不传代理时仍然会读取系统环境变量代理
    return urllib.request.build_opener()


def request(url: str, data: bytes | None = None, headers: dict | None = None,
            timeout: float = 12.0, proxy: str = "", method: str | None = None,
            direct: bool = False):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})},
                                 method=method or ("POST" if data is not None else "GET"))
    return opener(proxy, direct=direct).open(req, timeout=timeout)


def http_json(url: str, timeout: float = 12.0, proxy: str = "", headers: dict | None = None,
              data: bytes | None = None, direct: bool = False) -> dict:
    # TLS 握手被掐断/连接被重置时请求未必送达, 短重试是安全的(含生图 POST);
    # HTTPError(如 401/500)与超时不重试
    retryable = (ssl.SSLError, ConnectionResetError)
    last: Exception | None = None
    for attempt in range(3):
        try:
            with request(url, data=data, headers=headers, timeout=timeout,
                         proxy=proxy, direct=direct) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), retryable) and attempt < 2:
                last = e
                time.sleep(1 + attempt)
                continue
            raise
    raise last  # pragma: no cover


def http_bytes(url: str, timeout: float = 12.0, proxy: str = "") -> bytes:
    with request(url, timeout=timeout, proxy=proxy) as resp:
        return resp.read()


def reachable(url: str, timeout: float = 5.0, proxy: str = "", direct: bool = False) -> bool:
    try:
        with request(url, timeout=timeout, proxy=proxy, direct=direct) as resp:
            resp.read(64)
            return True
    except Exception:
        return False
