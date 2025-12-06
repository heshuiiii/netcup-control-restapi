#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Netcup 流量监控主控制器
使用新版 REST API 替代旧的 SOAP API
"""

import os
import json
import threading
import time
import requests
from datetime import datetime
from flask import Flask, jsonify, request
from logger import logger
from netcup_api import NetcupAPI
from qb_client import QBittorrentClient
from qb_rss import QBRSSClient
from telegram_notifier import TelegramNotifier
from apscheduler.schedulers.background import BackgroundScheduler


class NetcupTrafficMonitor:
    """Netcup 流量监控器 - 使用新版 REST API"""

    def __init__(self):
        # 读取脚本同目录的 config.json
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_file = os.path.join(script_dir, 'config.json')

        # 数据缓存 - 存储所有服务器的信息
        # 格式: {"ipv4_ip": {"ipv4IP": "xxx", "trafficThrottled": bool, "traffic_gb": float, ...}}
        self.cached_data = {}

        # 加载配置
        config = self.load_config()
        self.webhook_path = config.get('webhook_path', '/webhook/secret-monitor')
        self.port = config.get('port', 56578)
        self.accounts = config.get('rest_accounts', [])  # 新版 API 账户配置

        # Vertex 相关配置(可选,但本需求需要)
        vconf = config.get('vertex', {})
        self.vertex_base_url = vconf.get('base_url', '')
        self.vertex_cookie = vconf.get('cookie', '')

        self.qb_rss = None
        if self.vertex_base_url:
            self.qb_rss = QBRSSClient(base=self.vertex_base_url, cookie=self.vertex_cookie)

        # Telegram 配置
        tg_config = config.get('telegram', {})
        self.telegram_bot_token = tg_config.get('bot_token', '')
        self.telegram_chat_id = tg_config.get('chat_id', '')
        self.telegram_enabled = bool(self.telegram_bot_token and self.telegram_chat_id)
        
        self.telegram_notifier = None
        if self.telegram_enabled:
            self.telegram_notifier = TelegramNotifier(
                bot_token=self.telegram_bot_token,
                chat_id=self.telegram_chat_id
            )
            logger.info("[Telegram] 通知功能已启用")
        else:
            logger.warning("[Telegram] 通知功能未配置或已禁用")

        # 创建 Flask 应用
        self.app = Flask(__name__)
        self.setup_routes()

        # 启动数据收集线程
        self.data_thread = threading.Thread(target=self.data_collection_loop, daemon=True)
        self.data_thread.start()

        # 启动定时任务调度器 (用于 Telegram 通知)
        if self.telegram_enabled and self.vertex_base_url:
            self.scheduler = BackgroundScheduler(timezone='Asia/Shanghai')
            # 每天的57分执行 Vertex 统计报告
            self.scheduler.add_job(
                func=self.send_vertex_daily_report,
                trigger='cron',
                minute=57,
                id='vertex_daily_report'
            )
            self.scheduler.start()
            logger.info("[调度器] Vertex 日报任务已启动 (每小时57分执行)")
        else:
            self.scheduler = None
            logger.warning("[调度器] Telegram 或 Vertex 未配置,日报任务未启动")

        logger.info("=" * 60)
        logger.info("NetcupTrafficMonitor 初始化完成")
        logger.info(f"Webhook路径: {self.webhook_path}")
        logger.info(f"端口: {self.port}")
        logger.info(f"配置文件: {self.config_file}")
        logger.info(f"加载了 {len(self.accounts)} 个账户")
        logger.info(f"Vertex: base_url={self.vertex_base_url}")
        logger.info(f"Vertex cookie configured: {bool(self.vertex_cookie)}")
        logger.info(f"Telegram 通知: {'已启用' if self.telegram_enabled else '未启用'}")
        logger.info("=" * 60)

    def load_config(self):
        """加载配置文件"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config
        except FileNotFoundError:
            logger.error(f"配置文件 {self.config_file} 不存在,请创建配置文件")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"配置文件JSON格式错误: {e}")
            return {}
        except Exception as e:
            logger.error(f"加载配置文件时发生错误: {e}")
            return {}

    def fetch_vertex_run_info(self) -> dict:
        """
        获取 Vertex 运行信息
        
        Returns:
            dict: API 返回的数据,格式: {"success": bool, "data": {...}}
        """
        if not self.vertex_base_url or not self.vertex_cookie:
            logger.error("[Vertex] 未配置 base_url 或 cookie,无法获取运行信息")
            return {"success": False, "error": "配置缺失"}

        try:
            api_url = f"{self.vertex_base_url}/api/setting/getRunInfo"
            headers = {
                "Cookie": self.vertex_cookie,
                "User-Agent": "Mozilla/5.0"
            }
            
            logger.info(f"[Vertex] 正在请求运行信息: {api_url}")
            response = requests.get(api_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            logger.info(f"[Vertex] 成功获取运行信息")
            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[Vertex] 请求运行信息失败: {e}")
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"[Vertex] 获取运行信息时发生错误: {e}")
            return {"success": False, "error": str(e)}

    def send_vertex_daily_report(self):
        """
        发送 Vertex 每日运行报告到 Telegram
        这个函数会被定时任务调用
        """
        logger.info("[定时任务] 开始生成 Vertex 日报")
        
        if not self.telegram_notifier:
            logger.warning("[定时任务] Telegram 未配置,跳过日报发送")
            return

        try:
            # 获取 Vertex 运行信息
            run_info = self.fetch_vertex_run_info()
            
            if not run_info.get('success'):
                error_msg = run_info.get('error', '未知错误')
                logger.error(f"[定时任务] 获取 Vertex 信息失败: {error_msg}")
                
                # 发送错误通知
                self.telegram_notifier.send_message(
                    f"<b>❌ Vertex 日报生成失败</b>\n\n错误: {error_msg}"
                )
                return

            # 发送报告
            success = self.telegram_notifier.send_vertex_report(run_info)
            
            if success:
                logger.info("[定时任务] Vertex 日报发送成功")
            else:
                logger.error("[定时任务] Vertex 日报发送失败")
                
        except Exception as e:
            logger.error(f"[定时任务] 生成或发送 Vertex 日报时发生错误: {e}")

    def setup_routes(self):
        """设置Flask路由"""

        @self.app.route(self.webhook_path, methods=['GET', 'POST'])
        def webhook():
            try:
                # 获取 ipv4IP 参数
                ipv4_ip = request.args.get('ipv4IP')
                if not ipv4_ip:
                    return jsonify({"error": "缺少ipv4IP参数"}), 400

                # 从缓存中查找对应的数据
                if ipv4_ip in self.cached_data:
                    return jsonify(self.cached_data[ipv4_ip])
                else:
                    return jsonify({"error": f"未找到IP {ipv4_ip} 的信息"}), 404

            except Exception as e:
                logger.error(f"处理webhook请求时发生错误: {e}")
                return jsonify({"error": "内部服务器错误"}), 500

        @self.app.route('/api/status', methods=['GET'])
        def api_status():
            """返回所有服务器状态(供Web面板使用)"""
            try:
                servers = []
                for ip, data in self.cached_data.items():
                    servers.append(data)

                return jsonify({
                    "success": True,
                    "data": {
                        "last_update": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        "total_servers": len(servers),
                        "throttled_count": sum(1 for s in servers if s.get('trafficThrottled')),
                        "normal_count": sum(1 for s in servers if not s.get('trafficThrottled')),
                        "servers": servers
                    }
                })
            except Exception as e:
                logger.error(f"获取状态时发生错误: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route('/api/vertex/report', methods=['GET'])
        def vertex_report():
            """手动触发 Vertex 报告发送"""
            try:
                if not self.telegram_notifier:
                    return jsonify({"success": False, "error": "Telegram 未配置"}), 400

                run_info = self.fetch_vertex_run_info()
                
                if not run_info.get('success'):
                    return jsonify({"success": False, "error": "获取 Vertex 信息失败"}), 500

                success = self.telegram_notifier.send_vertex_report(run_info)
                
                if success:
                    return jsonify({"success": True, "message": "报告发送成功"})
                else:
                    return jsonify({"success": False, "error": "报告发送失败"}), 500

            except Exception as e:
                logger.error(f"手动触发 Vertex 报告时发生错误: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        @self.app.route('/health', methods=['GET'])
        def health():
            return jsonify({
                "status": "ok",
                "timestamp": datetime.now().isoformat(),
                "total_servers": len(self.cached_data),
                "telegram_enabled": self.telegram_enabled
            })

        @self.app.route('/', methods=['GET'])
        def dashboard():
            """Web监控面板"""
            return self.render_dashboard()

    def get_server_info_from_account(self, account_config: dict) -> dict:
        """
        从单个账户自动获取所有服务器信息

        Args:
            account_config: 账户配置,包含 account_id, access_token, refresh_token

        Returns:
            {ip: {server_data}} 字典
        """
        server_data = {}

        try:
            # 初始化 API 客户端
            api = NetcupAPI(
                account_id=account_config['account_id'],
                access_token=account_config['access_token'],
                refresh_token=account_config['refresh_token']
            )

            # 自动获取账户下的所有服务器
            servers_list = api.get_servers()

            if not servers_list:
                logger.warning(f"[{account_config['account_id']}] 未找到任何服务器或获取失败")
                return server_data

            logger.info(f"[{account_config['account_id']}] 发现 {len(servers_list)} 台服务器")

            # 遍历所有服务器
            for server in servers_list:
                server_id = server.get('vserverId') or server.get('id')
                server_name = server.get('hostname') or server.get('name') or server_id

                if not server_id:
                    continue

                try:
                    # 获取服务器 IP
                    ipv4 = api.get_server_ipv4(server_id)
                    if not ipv4:
                        logger.warning(f"[{account_config['account_id']}] 无法获取服务器 {server_name} 的IP")
                        continue

                    # 获取服务器状态
                    status = api.get_server_status(server_id)

                    # 检查流量限速
                    is_throttled, traffic_info = api.check_traffic_throttled(server_id)

                    if is_throttled is None:
                        logger.warning(f"[{account_config['account_id']}] 无法获取服务器 {server_name} 的限速状态")
                        continue

                    # 构建服务器数据
                    server_data[ipv4] = {
                        "ipv4IP": ipv4,
                        "trafficThrottled": is_throttled,
                        "status": status or "UNKNOWN",
                        "traffic_gb": traffic_info.get('total_gb', 0),
                        "rx_gb": round(traffic_info.get('total_rx_mib', 0) / 1024, 2),
                        "tx_gb": round(traffic_info.get('total_tx_mib', 0) / 1024, 2),
                        "account_id": account_config['account_id'],
                        "server_id": server_id,
                        "server_name": server_name,
                        "last_check_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }

                    logger.info(
                        f"[{account_config['account_id']}] {server_name}({ipv4}) - "
                        f"限速: {is_throttled}, 流量: {traffic_info.get('total_gb', 0)}GB"
                    )

                except Exception as e:
                    logger.error(f"[{account_config['account_id']}] 获取服务器 {server_name} 信息失败: {e}")
                    continue

        except Exception as e:
            logger.error(f"从账户 {account_config.get('account_id')} 获取服务器信息失败: {e}")

        return server_data

    def enable_downloader(self, ip: str):
        """启用下载器"""
        if self.qb_rss:
            try:
                r = self.qb_rss.enable_downloader(ip)
                logger.info(f"[Vertex] 启用下载器({ip}): {r}")
            except Exception as e:
                logger.error(f"[Vertex] 启用下载器({ip})失败: {e}")

    def disable_downloader(
            self,
            ip: str,
            url: str = None,
            username: str = None,
            password: str = None,
    ):
        """禁用下载器并清理任务"""
        # 1. 暂停 Vertex 下载器
        if self.qb_rss:
            try:
                r = self.qb_rss.pause_downloader(ip)
                logger.info(f"[Vertex] 暂停下载器({ip}): {r}")
            except Exception as e:
                logger.error(f"[Vertex] 暂停下载器({ip})失败: {e}")

        # 2. 暂停并删除 qBittorrent 任务
        if url and username and password:
            try:
                qb = QBittorrentClient(url, username, password)
                qb.pause_all()
                time.sleep(5)
                qb.delete_all(delete_files=True)
                logger.info(f"[qBittorrent] 已暂停并删除 {ip} 的所有任务")
            except Exception as e:
                logger.error(f"[qBittorrent] 暂停 {ip} 所有任务失败: {e}")

    def update_cached_data(self):
        """更新缓存的数据,并在状态变化时联动 Vertex 下载器"""
        try:
            new_data = {}

            # 遍历所有配置的账户
            for account in self.accounts:
                if not all(k in account for k in ['account_id', 'access_token', 'refresh_token']):
                    logger.warning(f"账户配置不完整,跳过: {account}")
                    continue

                account_data = self.get_server_info_from_account(account)
                new_data.update(account_data)

            # 对比新旧状态,检测变化并联动下载器
            for ip, payload in new_data.items():
                new_throttled = payload.get("trafficThrottled")
                old_throttled = self.cached_data.get(ip, {}).get("trafficThrottled")

                # 获取 qBittorrent 连接信息
                url, username, password = None, None, None
                if self.qb_rss:
                    url, username, password = self.qb_rss.get_user_info(ip)

                if old_throttled is None:
                    # 首次发现
                    logger.info(f"[状态监听] 首次发现 {ip}, trafficThrottled={new_throttled}")

                    try:
                        if new_throttled is False:
                            logger.info(f"[首次-Vertex] 启用下载器({ip})")
                            self.enable_downloader(ip)
                        elif new_throttled is True:
                            logger.info(f"[首次-Vertex] 暂停下载器({ip})")
                            self.disable_downloader(ip, url, username, password)
                    except Exception as e:
                        logger.error(f"[首次-联动] 处理 {ip} 时出错: {e}")

                elif old_throttled != new_throttled:
                    # 状态变化
                    logger.warning(f"[状态变化] {ip}: {old_throttled} -> {new_throttled}")

                    try:
                        if old_throttled is True and new_throttled is False:
                            # 解除限速 -> 启用下载器
                            logger.info(f"[Vertex] 启用下载器({ip})")
                            self.enable_downloader(ip)
                        elif old_throttled is False and new_throttled is True:
                            # 被限速 -> 暂停下载器和任务
                            logger.info(f"[Vertex] 暂停下载器({ip})")
                            self.disable_downloader(ip, url, username, password)
                    except Exception as e:
                        logger.error(f"[联动] 处理 {ip} 的状态变化时出错: {e}")
                else:
                    logger.debug(f"[状态监听] {ip} 未变化: {new_throttled}")

            # 更新缓存
            self.cached_data = new_data
            logger.info(f"数据更新成功,共缓存 {len(self.cached_data)} 个服务器信息")

        except Exception as e:
            logger.error(f"更新缓存数据时发生错误: {e}")

    def data_collection_loop(self):
        """数据收集循环,每5分钟执行一次"""
        logger.info("数据收集线程已启动")

        # 立即执行一次数据更新
        self.update_cached_data()

        while True:
            try:
                time.sleep(300)  # 5分钟 = 300秒
                self.update_cached_data()
            except Exception as e:
                logger.error(f"数据收集循环中发生错误: {e}")
                time.sleep(60)  # 发生错误时等待1分钟后重试

    def render_dashboard(self):
        """渲染 Web 监控面板 - 从外部 HTML 文件读取"""
        try:
            # 尝试读取外部 HTML 文件
            html_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard.html')

            if os.path.exists(html_file):
                with open(html_file, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                logger.info(f"成功加载外部 HTML 文件: {html_file}")
                return html_content
            else:
                # 如果外部文件不存在,使用内置的简化版本
                logger.warning(f"未找到外部 HTML 文件: {html_file}, 使用内置版本")
                return self._get_builtin_html()

        except Exception as e:
            logger.error(f"读取 HTML 文件时出错: {e}, 使用内置版本")
            return self._get_builtin_html()

    def _get_builtin_html(self):
        """内置的简化版 HTML(当外部文件不存在时使用)"""
        return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Netcup 流量监控面板</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        .header {
            background: white;
            padding: 30px;
            border-radius: 15px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }
        .header h1 { font-size: 32px; color: #333; margin-bottom: 20px; }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 25px;
            border-radius: 12px;
            text-align: center;
        }
        .stat-card h3 { font-size: 14px; opacity: 0.9; margin-bottom: 10px; }
        .stat-card .value { font-size: 42px; font-weight: bold; }
        .stat-card.warning { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }
        .stat-card.success { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }
        .servers-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
            gap: 20px;
        }
        .server-card {
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.1);
            transition: all 0.3s;
        }
        .server-card:hover { transform: translateY(-5px); }
        .server-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 2px solid #f0f0f0;
        }
        .server-title { font-size: 18px; font-weight: 700; color: #333; }
        .badge {
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
            color: white;
        }
        .badge.throttled { background: #f59e0b; }
        .badge.normal { background: #10b981; }
        .server-info { display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; }
        .info-item { background: #f9fafb; padding: 12px; border-radius: 8px; }
        .info-label { font-size: 11px; color: #6b7280; margin-bottom: 5px; }
        .info-value { font-size: 18px; font-weight: 700; color: #111827; }
        .loading { text-align: center; padding: 50px; color: white; font-size: 18px; }
        .last-update { text-align: center; color: white; margin-top: 30px; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🖥️ Netcup 流量监控面板</h1>
            <div id="stats" class="stats"></div>
        </div>
        <div id="servers" class="servers-grid"></div>
        <div id="loading" class="loading">正在加载数据...</div>
        <div class="last-update" id="lastUpdate"></div>
    </div>
    <script>
        const API_URL = '/api/status';
        const REFRESH_INTERVAL = 10000;
        let currentData = null;

        async function fetchData() {
            try {
                const response = await fetch(API_URL);
                const result = await response.json();
                if (result.success) {
                    currentData = result.data;
                    updateView();
                }
            } catch (error) {
                console.error('加载数据失败:', error);
            } finally {
                document.getElementById('loading').style.display = 'none';
            }
        }

        function updateView() {
            if (!currentData) return;
            document.getElementById('stats').innerHTML = `
                <div class="stat-card">
                    <h3>总服务器</h3>
                    <div class="value">${currentData.total_servers}</div>
                </div>
                <div class="stat-card warning">
                    <h3>限速中</h3>
                    <div class="value">${currentData.throttled_count}</div>
                </div>
                <div class="stat-card success">
                    <h3>正常运行</h3>
                    <div class="value">${currentData.normal_count}</div>
                </div>
            `;
            document.getElementById('servers').innerHTML = currentData.servers.map(s => `
                <div class="server-card">
                    <div class="server-header">
                        <div class="server-title">${s.server_name}</div>
                        <span class="badge ${s.trafficThrottled ? 'throttled' : 'normal'}">
                            ${s.trafficThrottled ? '🔴 限速' : '🟢 正常'}
                        </span>
                    </div>
                    <div class="server-info">
                        <div class="info-item">
                            <div class="info-label">IP地址</div>
                            <div class="info-value">${s.ipv4IP}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">总流量</div>
                            <div class="info-value">${s.traffic_gb} GB</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">上传</div>
                            <div class="info-value">${s.tx_gb} GB</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">下载</div>
                            <div class="info-value">${s.rx_gb} GB</div>
                        </div>
                    </div>
                </div>
            `).join('');
            document.getElementById('lastUpdate').textContent = `最后更新: ${currentData.last_update}`;
        }

        fetchData();
        setInterval(fetchData, REFRESH_INTERVAL);
    </script>
</body>
</html>
        """

    def run(self):
        """启动Flask应用"""
        logger.info(f"启动Web服务,端口: {self.port}")
        logger.info(f"Webhook URL: http://localhost:{self.port}{self.webhook_path}")
        logger.info(f"监控面板: http://localhost:{self.port}/")
        logger.info(f"手动触发 Vertex 报告: http://localhost:{self.port}/api/vertex/report")
        self.app.run(host='0.0.0.0', port=self.port, debug=False)


def main():
    monitor = NetcupTrafficMonitor()
    monitor.run()


if __name__ == '__main__':
    main()
