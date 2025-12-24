#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Netcup REST API 客户端模块
负责服务器状态检测和流量监控
"""

import requests
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from logger import logger


class NetcupAPI:
    """Netcup SCP REST API 客户端"""

    def __init__(
        self,
        account_id: str,
        access_token: str,
        refresh_token: str,
        base_url: str = "https://www.servercontrolpanel.de/scp-core/api/v1",
        keycloak_url: str = "https://www.servercontrolpanel.de/realms/scp/protocol/openid-connect/token"
    ):
        self.account_id = account_id
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.base_url = base_url
        self.keycloak_url = keycloak_url
        self.client_id = "scp"

        # Token 过期时间管理
        self.access_token_expires_at = datetime.now() + timedelta(minutes=4)
        self.token_refresh_lock = threading.Lock()

        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/hal+json"
        }

    def is_token_expired(self) -> bool:
        """检查 access token 是否即将过期(提前30秒刷新)"""
        return datetime.now() >= (self.access_token_expires_at - timedelta(seconds=30))

    def refresh_access_token(self) -> bool:
        """刷新 access token"""
        with self.token_refresh_lock:
            try:
                logger.info(f"[{self.account_id}] 正在刷新 access token...")

                data = {
                    'client_id': self.client_id,
                    'refresh_token': self.refresh_token,
                    'grant_type': 'refresh_token'
                }

                response = requests.post(
                    self.keycloak_url,
                    data=data,
                    headers={'Content-Type': 'application/x-www-form-urlencoded'},
                    timeout=30
                )

                if response.status_code == 200:
                    token_data = response.json()

                    self.access_token = token_data.get('access_token')
                    self.headers["Authorization"] = f"Bearer {self.access_token}"

                    new_refresh_token = token_data.get('refresh_token')
                    if new_refresh_token:
                        self.refresh_token = new_refresh_token

                    expires_in = token_data.get('expires_in', 300)
                    self.access_token_expires_at = datetime.now() + timedelta(seconds=expires_in)

                    logger.info(f"[{self.account_id}] Access token 刷新成功 (有效期: {expires_in}秒)")
                    return True
                else:
                    logger.error(f"[{self.account_id}] 刷新 token 失败: {response.status_code}")
                    return False

            except Exception as e:
                logger.error(f"[{self.account_id}] 刷新 token 异常: {e}")
                return False

    def _ensure_valid_token(self) -> bool:
        """确保 token 有效"""
        if self.is_token_expired():
            return self.refresh_access_token()
        return True

    def _make_request(
        self,
        method: str,
        endpoint: str,
        max_retries: int = 2,
        **kwargs
    ) -> Optional[requests.Response]:
        """通用请求方法,支持自动重试和 Token 刷新"""
        url = f"{self.base_url}{endpoint}"

        for attempt in range(max_retries + 1):
            try:
                if not self._ensure_valid_token():
                    return None

                response = requests.request(
                    method,
                    url,
                    headers=self.headers,
                    timeout=30,
                    **kwargs
                )

                # 处理 401 未授权,尝试刷新 Token
                if response.status_code == 401:
                    if attempt < max_retries:
                        if self.refresh_access_token():
                            continue
                        else:
                            return None
                    else:
                        return None

                return response

            except requests.exceptions.Timeout:
                if attempt < max_retries:
                    time.sleep(2)
                    continue
                logger.error(f"[{self.account_id}] 请求超时: {url}")
                return None

            except Exception as e:
                logger.error(f"[{self.account_id}] 请求异常: {e}")
                if attempt < max_retries:
                    time.sleep(2)
                    continue
                return None

        return None

    def get_servers(self) -> Optional[List[Dict]]:
        """获取所有服务器列表"""
        response = self._make_request("GET", "/servers")
        if response and response.status_code == 200:
            return response.json()
        return None

    def get_server_details(self, server_id: str, load_live_info: bool = True) -> Optional[Dict]:
        """
        获取服务器详细信息
        
        Args:
            server_id: 服务器ID
            load_live_info: 是否加载实时信息(状态、流量等)
        """
        params = {"loadServerLiveInfo": "true"} if load_live_info else {}
        response = self._make_request("GET", f"/servers/{server_id}", params=params)

        if response and response.status_code == 200:
            return response.json()
        return None

    def get_server_status(self, server_id: str) -> Optional[str]:
        """获取服务器运行状态"""
        server_details = self.get_server_details(server_id, load_live_info=True)
        if server_details:
            server_live_info = server_details.get('serverLiveInfo', {})
            return server_live_info.get('state', 'UNKNOWN')
        return None

    def get_server_ipv4(self, server_id: str) -> Optional[str]:
        """
        获取服务器的主 IPv4 地址

        Args:
            server_id: 服务器ID

        Returns:
            IPv4地址,如果没有则返回None
        """
        try:
            server_details = self.get_server_details(server_id, load_live_info=False)
            if not server_details:
                return None

            ipv4_addresses = server_details.get('ipv4Addresses', [])
            if ipv4_addresses and len(ipv4_addresses) > 0:
                return ipv4_addresses[0].get('ip')

            return None

        except Exception as e:
            logger.error(f"[{self.account_id}] 获取服务器IP异常: {e}")
            return None

    def check_traffic_throttled(self, server_id: str) -> Tuple[Optional[bool], Dict]:
        """
        检查服务器是否被流量限速
        
        Returns:
            (是否限速, 流量详情字典)
            
        流量详情包含:
            - total_rx_mib: 总下载流量(MiB)
            - total_tx_mib: 总上传流量(MiB)
            - total_gb: 总流量(GB)
            - interfaces: 接口详细信息列表
        """
        try:
            server_details = self.get_server_details(server_id, load_live_info=True)
            if not server_details:
                return None, {}

            server_live_info = server_details.get('serverLiveInfo', {})
            interfaces = server_live_info.get('interfaces', [])

            is_throttled = False
            traffic_info = {
                'total_rx_mib': 0,
                'total_tx_mib': 0,
                'interfaces': []
            }

            for interface in interfaces:
                rx = interface.get('rxMonthlyInMiB', 0)
                tx = interface.get('txMonthlyInMiB', 0)
                
                traffic_info['total_rx_mib'] += rx
                traffic_info['total_tx_mib'] += tx
                
                if interface.get('trafficThrottled', False):
                    is_throttled = True
                
                traffic_info['interfaces'].append({
                    'mac': interface.get('mac', 'unknown'),
                    'rx_mib': rx,
                    'tx_mib': tx,
                    'throttled': interface.get('trafficThrottled', False)
                })

            # 转换为 GB
            traffic_info['total_gb'] = round(
                (traffic_info['total_rx_mib'] + traffic_info['total_tx_mib']) / 1024,
                2
            )

            return is_throttled, traffic_info

        except Exception as e:
            logger.error(f"[{self.account_id}] 检查流量限速异常: {e}")
            return None, {}

    def get_token_info(self) -> Dict:
        """获取当前 token 信息(用于调试)"""
        return {
            'access_token': self.access_token[:20] + "...",  # 只显示前20字符
            'refresh_token': self.refresh_token[:20] + "...",
            'expires_at': self.access_token_expires_at.isoformat()
        }


class ServerController:
    """服务器控制器 - 负责开关机操作"""
    
    def __init__(self, api: NetcupAPI):
        self.api = api
    
    def stop_server(self, server_id: str, max_retries: int = 3) -> bool:
        """关闭服务器"""
        for attempt in range(max_retries):
            try:
                url = f"/servers/{server_id}"
                params = {"stateOption": "POWEROFF"}
                data = {"state": "OFF"}

                headers = self.api.headers.copy()
                headers["Content-Type"] = "application/merge-patch+json"

                response = requests.patch(
                    f"{self.api.base_url}{url}",
                    params=params,
                    json=data,
                    headers=headers,
                    timeout=30
                )

                if response.status_code in [200, 202, 204]:
                    logger.info(f"[{self.api.account_id}] ✅ 服务器 {server_id} 关机成功")
                    return True
                else:
                    logger.warning(
                        f"[{self.api.account_id}] 关机失败 "
                        f"(尝试 {attempt + 1}/{max_retries}): {response.status_code}"
                    )

            except Exception as e:
                logger.error(
                    f"[{self.api.account_id}] 关机异常 "
                    f"(尝试 {attempt + 1}/{max_retries}): {e}"
                )
            
            if attempt < max_retries - 1:
                time.sleep(3)
        
        logger.error(f"[{self.api.account_id}] ❌ 服务器 {server_id} 关机失败(超过最大重试次数)")
        return False

    def start_server(self, server_id: str, max_retries: int = 3) -> bool:
        """启动服务器"""
        for attempt in range(max_retries):
            try:
                url = f"/servers/{server_id}"
                data = {"state": "ON"}

                headers = self.api.headers.copy()
                headers["Content-Type"] = "application/merge-patch+json"

                response = requests.patch(
                    f"{self.api.base_url}{url}",
                    json=data,
                    headers=headers,
                    timeout=30
                )

                if response.status_code in [200, 202, 204]:
                    logger.info(f"[{self.api.account_id}] ✅ 服务器 {server_id} 开机成功")
                    return True
                else:
                    logger.warning(
                        f"[{self.api.account_id}] 开机失败 "
                        f"(尝试 {attempt + 1}/{max_retries}): {response.status_code}"
                    )

            except Exception as e:
                logger.error(
                    f"[{self.api.account_id}] 开机异常 "
                    f"(尝试 {attempt + 1}/{max_retries}): {e}"
                )
            
            if attempt < max_retries - 1:
                time.sleep(3)
        
        logger.error(f"[{self.api.account_id}] ❌ 服务器 {server_id} 开机失败(超过最大重试次数)")
        return False