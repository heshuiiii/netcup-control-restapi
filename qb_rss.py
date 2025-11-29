import json
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

class QBRSSClient:
    """
    负责启用/暂停 Vertex 的下载器（通常对应某台 qB 客户端）。
    设计成与 QBittorrentClient 相似的类形态，便于在其它模块中直接实例化调用。
    """
    def __init__(self, base: str, cookie: str = ""):
        self.base = (base or "").rstrip("/")
        self.cookie = cookie or ""
        self.headers = {"Accept": "application/json"}
        if self.cookie:
            self.headers["Cookie"] = self.cookie

    # ----------------- 内部 HTTP 工具 -----------------
    def _http_get_json(self, url: str) -> dict:
        req = Request(url, headers=self.headers, method="GET")
        with urlopen(req, timeout=30) as resp:
            data = resp.read()
        return json.loads(data.decode("utf-8"))

    def _http_post_json(self, url: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        h = dict(self.headers)
        h["Content-Type"] = "application/json"
        req = Request(url, data=body, headers=h, method="POST")
        with urlopen(req, timeout=45) as resp:
            raw = resp.read()
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                return {"text": raw.decode("utf-8", "ignore")}

    @staticmethod
    def _extract_host(client_url: str) -> str | None:
        if not isinstance(client_url, str):
            return None
        # 优先解析标准 URL
        try:
            host = urlsplit(client_url).hostname
            if host:
                return host
        except Exception:
            pass
        if "://" not in client_url and ":" in client_url:
            return client_url.split(":")[0]
        return None

    @staticmethod
    def _find_downloader(downloaders: list, key: str) -> dict | None:
        """
        key 可以是下载器ID，或 IP（将与 clientUrl 的 hostname 匹配）。
        返回完整的下载器对象。
        """
        # 先当作ID精确匹配
        for d in downloaders:
            if d.get("id") == key or d.get("_id") == key:
                return d
        # 再按 IP/hostname 匹配 clientUrl
        for d in downloaders:
            cu = d.get("clientUrl") or d.get("url") or ""
            host = QBRSSClient._extract_host(cu) if cu else None
            if host == key or (isinstance(cu, str) and key in cu):
                return d
        return None
        
    def get_qb_info(self, ip_or_id: str):            
        # 1) 拉取下载器列表
        dlist = self._http_get_json(f"{self.base}/api/downloader/list")
        downloaders = dlist.get("data") if isinstance(dlist, dict) else dlist
        if not isinstance(downloaders, list):
            return {"ok": False, "detail": "Unexpected /api/downloader/list response"}

        # 2) 定位目标下载器
        target = self._find_downloader(downloaders, ip_or_id)

        return target
        
        
    def get_user_info(self, ip:str):
        target = self.get_qb_info(ip)
        if not target:
            return None, None, None
            
        url = target.get("clientUrl") or target.get("url") or None
        username = target.get("username") or target.get("user") or target.get("login") or None
        password = target.get("password") or target.get("pass") or None
        
        return (url, username, password)

    # ----------------- 对外能力 -----------------
    def set_downloader_enabled(self, ip_or_id: str, enabled: bool) -> dict:
        """
        启用/禁用（暂停） Vertex 下载器。
        - ip_or_id: 可以传 IP（匹配 downloader.clientUrl 的 hostname），也可以直接传下载器ID
        - enabled: True=启用, False=禁用(暂停)
        返回：{"ok": True/False, "id": "...", "alias": "...", "verify": {"enable": ..., "enabled": ...}, "detail": ...}
        """
        
        if not self.base:
            return {"ok": False, "detail": "base url not configured"}

        target = self.get_qb_info(ip_or_id)
        if not target:
            return {"ok": False, "detail": f"Downloader not found for key={ip_or_id}"}

        did = target.get("id") or target.get("_id")
        alias = target.get("alias")
        
        # 3) 提交修改（完整对象，避免丢字段；兼容 enable/enabled 命名差异）
        new_obj = dict(target)
        new_obj["enable"] = bool(enabled)   # 常见字段

        resp = self._http_post_json(f"{self.base}/api/downloader/modify", new_obj)

        # 4) 验证
        vlist = self._http_get_json(f"{self.base}/api/downloader/list")
        vdownloaders = vlist.get("data") if isinstance(vlist, dict) else vlist
        v = next((d for d in vdownloaders if (d.get("id") or d.get("_id")) == did), None)
        verify = {"enable": v.get("enable") if v else None, "enabled": v.get("enabled") if v else None}

        return {"ok": True, "id": did, "alias": alias, "verify": verify, "detail": resp}

    def pause_downloader(self, ip_or_id: str) -> dict:
        """暂停（禁用）下载器。"""
        return self.set_downloader_enabled(ip_or_id, False)

    def enable_downloader(self, ip_or_id: str) -> dict:
        """启用下载器。"""
        return self.set_downloader_enabled(ip_or_id, True)