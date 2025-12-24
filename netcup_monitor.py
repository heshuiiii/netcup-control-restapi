#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版 Netcup 流量监控控制器 - 修复版
添加了限速历史追踪和 Telegram 通知功能
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
    """增强版 Netcup 流量监控器"""

    def __init__(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_file = os.path.join(script_dir, 'config.json')
        self.history_file = os.path.join(script_dir, 'throttle_history.json')

        # 数据缓存
        self.cached_data = {}
        # 限速历史记录
        self.throttle_history = self.load_throttle_history()

        # 加载配置
        config = self.load_config()
        self.webhook_path = config.get('webhook_path', '/webhook/secret-monitor')
        self.port = config.get('port', 56578)
        self.accounts = config.get('rest_accounts', [])

        # Vertex 配置
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

        # 启动定时任务调度器
        if self.telegram_enabled and self.vertex_base_url:
            self.scheduler = BackgroundScheduler(timezone='Asia/Shanghai')
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
        logger.info(f"加载了 {len(self.accounts)} 个账户")
        logger.info(f"Telegram 通知: {'已启用' if self.telegram_enabled else '未启用'}")
        logger.info("=" * 60)

    def load_config(self):
        """加载配置文件"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载配置文件时发生错误: {e}")
            return {}

    def load_throttle_history(self):
        """加载限速历史记录"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.info(f"成功加载限速历史记录: {len(data)} 台服务器")
                    return data
            logger.info("限速历史文件不存在,将创建新的")
            return {}
        except Exception as e:
            logger.error(f"加载限速历史失败: {e}")
            return {}

    def save_throttle_history(self):
        """保存限速历史记录"""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.throttle_history, f, indent=2, ensure_ascii=False)
            logger.debug(f"限速历史已保存: {len(self.throttle_history)} 台服务器")
        except Exception as e:
            logger.error(f"保存限速历史失败: {e}")

    def update_throttle_history(self, ip: str, is_throttled: bool, server_name: str = ""):
        """更新限速历史并发送 Telegram 通知"""
        now = datetime.now()
        timestamp = now.timestamp()
        
        if ip not in self.throttle_history:
            self.throttle_history[ip] = {
                "server_name": server_name,
                "current_throttled": is_throttled,
                "last_throttle_time": None,
                "last_unthrottle_time": None,
                "throttle_count": 0,
                "total_throttled_seconds": 0,
                "history": []
            }
            logger.info(f"[历史记录] 为 {ip} ({server_name}) 创建新的历史记录")
        
        history = self.throttle_history[ip]
        old_throttled = history.get("current_throttled")
        
        # 更新服务器名称
        if server_name and history.get("server_name") != server_name:
            history["server_name"] = server_name
        
        # 状态变化时更新历史
        if old_throttled != is_throttled:
            logger.warning(f"[历史记录] {ip} 状态变化: {old_throttled} -> {is_throttled}")
            
            if is_throttled:
                # 被限速
                history["last_throttle_time"] = timestamp
                history["throttle_count"] += 1
                history["history"].append({
                    "event": "throttled",
                    "timestamp": timestamp,
                    "datetime": now.strftime('%Y-%m-%d %H:%M:%S')
                })
                
                logger.warning(f"[限速] {server_name or ip} 已被限速 (第 {history['throttle_count']} 次)")
                
                # 发送 Telegram 通知
                if self.telegram_notifier:
                    try:
                        message = (
                            f"🔴 <b>限速警告</b>\n\n"
                            f"服务器: <code>{server_name or ip}</code>\n"
                            f"IP: <code>{ip}</code>\n\n"
                            f"已被限速,下载器已暂停\n"
                            f"限速次数: 第 {history['throttle_count']} 次\n"
                            f"时间: {now.strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                        self.telegram_notifier.send_message(message)
                        logger.info(f"[Telegram] 限速通知已发送: {ip}")
                    except Exception as e:
                        logger.error(f"[Telegram] 发送限速通知失败: {e}")
                    
            else:
                # 解除限速
                history["last_unthrottle_time"] = timestamp
                
                # 计算本次限速持续时间
                duration_str = "未知"
                if history["last_throttle_time"]:
                    throttled_duration = int(timestamp - history["last_throttle_time"])
                    history["total_throttled_seconds"] += throttled_duration
                    duration_str = self.format_duration(throttled_duration)
                    
                    history["history"].append({
                        "event": "unthrottled",
                        "timestamp": timestamp,
                        "datetime": now.strftime('%Y-%m-%d %H:%M:%S'),
                        "duration_seconds": throttled_duration
                    })
                    
                    logger.info(f"[解除限速] {server_name or ip} 限速已解除,持续了 {duration_str}")
                    
                    # 发送 Telegram 通知
                    if self.telegram_notifier:
                        try:
                            message = (
                                f"🟢 <b>限速解除</b>\n\n"
                                f"服务器: <code>{server_name or ip}</code>\n"
                                f"IP: <code>{ip}</code>\n\n"
                                f"限速已解除,下载器已启用\n"
                                f"本次限速时长: <code>{duration_str}</code>\n"
                                f"累计限速: <code>{self.format_duration(history['total_throttled_seconds'])}</code>\n"
                                f"时间: {now.strftime('%Y-%m-%d %H:%M:%S')}"
                            )
                            self.telegram_notifier.send_message(message)
                            logger.info(f"[Telegram] 解除限速通知已发送: {ip}")
                        except Exception as e:
                            logger.error(f"[Telegram] 发送解除限速通知失败: {e}")
            
            history["current_throttled"] = is_throttled
            
            # 只保留最近100条历史记录
            if len(history["history"]) > 100:
                history["history"] = history["history"][-100:]
            
            self.save_throttle_history()

    @staticmethod
    def format_duration(seconds: int) -> str:
        """格式化时长"""
        if seconds < 60:
            return f"{seconds}秒"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            return f"{minutes}分{secs}秒"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}小时{minutes}分"

    def calculate_availability(self, ip: str) -> dict:
        """计算可用率统计"""
        if ip not in self.throttle_history:
            return {
                "throttle_count": 0,
                "total_throttled_time": "0秒",
                "last_throttle_time": None,
                "last_unthrottle_time": None,
                "current_throttle_duration": "0秒",
                "history": []
            }
        
        history = self.throttle_history[ip]
        now = datetime.now().timestamp()
        
        # 计算当前限速持续时间
        current_throttle_duration = 0
        if history.get("current_throttled") and history.get("last_throttle_time"):
            current_throttle_duration = int(now - history["last_throttle_time"])
        
        # 计算总限速时间（不包括当前正在进行的限速）
        total_throttled = history.get("total_throttled_seconds", 0)
        
        # 格式化时长为小时
        def format_hours(seconds):
            hours = seconds / 3600
            if hours >= 1:
                return f"{hours:.1f}小时"
            else:
                minutes = seconds / 60
                return f"{minutes:.0f}分钟"
        
        return {
            "throttle_count": history.get("throttle_count", 0),
            "total_throttled_time": format_hours(total_throttled),
            "last_throttle_time": datetime.fromtimestamp(history["last_throttle_time"]).strftime('%Y-%m-%d %H:%M:%S') if history.get("last_throttle_time") else None,
            "last_unthrottle_time": datetime.fromtimestamp(history["last_unthrottle_time"]).strftime('%Y-%m-%d %H:%M:%S') if history.get("last_unthrottle_time") else None,
            "current_throttle_duration": format_hours(current_throttle_duration) if current_throttle_duration > 0 else "0分钟",
            "history": history.get("history", [])
        }

    def bytes_to_tib(self, mib_value: float) -> float:
        """将 MiB 转换为 TiB"""
        return mib_value / (1024 * 1024)

    def setup_routes(self):
        """设置Flask路由"""

        @self.app.route(self.webhook_path, methods=['GET', 'POST'])
        def webhook():
            try:
                ipv4_ip = request.args.get('ipv4IP')
                if not ipv4_ip:
                    return jsonify({"error": "缺少ipv4IP参数"}), 400

                if ipv4_ip in self.cached_data:
                    return jsonify(self.cached_data[ipv4_ip])
                else:
                    return jsonify({"error": f"未找到IP {ipv4_ip} 的信息"}), 404

            except Exception as e:
                logger.error(f"处理webhook请求时发生错误: {e}")
                return jsonify({"error": "内部服务器错误"}), 500

        @self.app.route('/api/status', methods=['GET'])
        def api_status():
            """返回所有服务器状态"""
            try:
                servers = []
                for ip, data in self.cached_data.items():
                    # 添加可用率统计
                    availability = self.calculate_availability(ip)
                    enhanced_data = {**data, **availability}
                    servers.append(enhanced_data)

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
            """获取 Vertex 运行信息报告并发送到 Telegram"""
            try:
                # 检查是否启用 Telegram
                if not self.telegram_notifier:
                    return jsonify({
                        "success": False,
                        "error": "Telegram 通知未启用"
                    }), 400
                
                # 获取 Vertex 运行信息
                run_info = self.fetch_vertex_run_info()
                
                if not run_info.get('success'):
                    return jsonify({
                        "success": False,
                        "error": run_info.get('error', '获取运行信息失败')
                    }), 500
                
                # 发送到 Telegram
                send_success = self.telegram_notifier.send_vertex_report(run_info)
                
                if send_success:
                    return jsonify({
                        "success": True,
                        "message": "报告已发送到 Telegram",
                        "data": run_info.get('data', {})
                    })
                else:
                    return jsonify({
                        "success": False,
                        "error": "发送 Telegram 消息失败",
                        "data": run_info.get('data', {})
                    }), 500
                
            except Exception as e:
                logger.error(f"[/api/vertex/report] 获取报告时发生错误: {e}")
                return jsonify({
                    "success": False,
                    "error": str(e)
                }), 500

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



    def render_dashboard(self):
        """渲染 Web 监控面板"""
        try:
            html_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard.html')

            if os.path.exists(html_file):
                with open(html_file, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                logger.info(f"成功加载外部 HTML 文件: {html_file}")
                return html_content
            else:
                logger.warning(f"未找到外部 HTML 文件: {html_file}, 使用内置版本")
                return self._get_builtin_html()

        except Exception as e:
            logger.error(f"读取 HTML 文件时出错: {e}, 使用内置版本")
            return self._get_builtin_html()

    def _get_builtin_html(self):
        """内置的简化版 HTML"""
        return """
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>监控面板</title></head>
<body><h1>监控面板</h1><p>请检查 dashboard.html 文件是否存在</p></body>
</html>
        """

    def get_server_info_from_account(self, account_config: dict) -> dict:
        """从单个账户获取所有服务器信息"""
        server_data = {}

        try:
            api = NetcupAPI(
                account_id=account_config['account_id'],
                access_token=account_config['access_token'],
                refresh_token=account_config['refresh_token']
            )

            servers_list = api.get_servers()

            if not servers_list:
                logger.warning(f"[{account_config['account_id']}] 未找到任何服务器")
                return server_data

            logger.info(f"[{account_config['account_id']}] 发现 {len(servers_list)} 台服务器")

            for server in servers_list:
                server_id = server.get('vserverId') or server.get('id')
                server_name = server.get('hostname') or server.get('name') or server_id

                if not server_id:
                    continue

                try:
                    ipv4 = api.get_server_ipv4(server_id)
                    if not ipv4:
                        continue

                    status = api.get_server_status(server_id)
                    is_throttled, traffic_info = api.check_traffic_throttled(server_id)

                    if is_throttled is None:
                        continue

                    # 转换流量为 TiB (从 MiB)
                    rx_mib = traffic_info.get('total_rx_mib', 0)
                    tx_mib = traffic_info.get('total_tx_mib', 0)
                    rx_tib = self.bytes_to_tib(rx_mib)
                    tx_tib = self.bytes_to_tib(tx_mib)
                    total_tib = rx_tib + tx_tib

                    server_data[ipv4] = {
                        "ipv4IP": ipv4,
                        "trafficThrottled": is_throttled,
                        "status": status or "UNKNOWN",
                        "traffic_tib": round(total_tib, 3),
                        "rx_tib": round(rx_tib, 3),
                        "tx_tib": round(tx_tib, 3),
                        "account_id": account_config['account_id'],
                        "server_id": server_id,
                        "server_name": server_name,
                        "last_check_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }

                    logger.info(
                        f"[{account_config['account_id']}] {server_name}({ipv4}) - "
                        f"限速: {is_throttled}, 流量: {round(total_tib, 3)} TiB"
                    )

                except Exception as e:
                    logger.error(f"获取服务器 {server_name} 信息失败: {e}")
                    continue

        except Exception as e:
            logger.error(f"从账户获取服务器信息失败: {e}")

        return server_data

    def enable_downloader(self, ip: str):
        """启用下载器并恢复种子状态"""
        # 1. 启用 Vertex 下载器
        if self.qb_rss:
            try:
                r = self.qb_rss.enable_downloader(ip)
                logger.info(f"[Vertex] 启用下载器({ip}): {r}")
            except Exception as e:
                logger.error(f"[Vertex] 启用下载器({ip})失败: {e}")

        # 2. 恢复 qBittorrent 中的种子
        if self.qb_rss:
            try:
                url, username, password = self.qb_rss.get_user_info(ip)
                if url and username and password:
                    qb = QBittorrentClient(url, username, password)
                    # 直接恢复所有暂停的种子
                    qb.client.torrents.resume.all()
                    logger.info(f"[qBittorrent] 已恢复 {ip} 的所有种子下载")
                else:
                    logger.warning(f"[qBittorrent] 无法获取 {ip} 的连接信息")
            except Exception as e:
                logger.error(f"[qBittorrent] 恢复 {ip} 种子失败: {e}")




    def disable_downloader(self, ip: str, url: str = None, username: str = None, password: str = None):
        """禁用下载器并暂停种子（不删除）"""
        # 1. 禁用 Vertex 下载器
        if self.qb_rss:
            try:
                r = self.qb_rss.pause_downloader(ip)
                logger.info(f"[Vertex] 暂停下载器({ip}): {r}")
            except Exception as e:
                logger.error(f"[Vertex] 暂停下载器({ip})失败: {e}")

        # 2. 暂停 qBittorrent 中的种子（不删除文件）
        if url and username and password:
            try:
                qb = QBittorrentClient(url, username, password)
                # 使用汇报+暂停的方法（不删除任何文件）
                qb.pause_all_with_reannounce()
                logger.info(f"[qBittorrent] 已暂停 {ip} 的所有种子（保留文件）")
            except Exception as e:
                logger.error(f"[qBittorrent] 暂停 {ip} 种子失败: {e}")

        elif self.qb_rss:
            # 如果没有直接传入连接信息，尝试从 Vertex 获取
            try:
                url, username, password = self.qb_rss.get_user_info(ip)
                if url and username and password:
                    qb = QBittorrentClient(url, username, password)
                    qb.pause_all_with_reannounce()
                    logger.info(f"[qBittorrent] 已暂停 {ip} 的所有种子（保留文件）")
                else:
                    logger.warning(f"[qBittorrent] 无法获取 {ip} 的连接信息，跳过种子暂停")
            except Exception as e:
                logger.error(f"[qBittorrent] 暂停 {ip} 种子失败: {e}")


    def update_cached_data(self):
        """更新缓存的数据"""
        try:
            new_data = {}

            for account in self.accounts:
                if not all(k in account for k in ['account_id', 'access_token', 'refresh_token']):
                    continue

                account_data = self.get_server_info_from_account(account)
                new_data.update(account_data)

            # 对比新旧状态
            for ip, payload in new_data.items():
                new_throttled = payload.get("trafficThrottled")
                old_throttled = self.cached_data.get(ip, {}).get("trafficThrottled")
                server_name = payload.get("server_name", "")

                url, username, password = None, None, None
                if self.qb_rss:
                    url, username, password = self.qb_rss.get_user_info(ip)

                if old_throttled is None:
                    # 首次发现
                    logger.info(f"[首次] {ip} ({server_name}), 限速={new_throttled}")
                    self.update_throttle_history(ip, new_throttled, server_name)

                    try:
                        if new_throttled is False:
                            self.enable_downloader(ip)
                        elif new_throttled is True:
                            self.disable_downloader(ip, url, username, password)
                    except Exception as e:
                        logger.error(f"[首次联动] {ip} 出错: {e}")

                elif old_throttled != new_throttled:
                    # 状态变化
                    logger.warning(f"[状态变化] {ip}: {old_throttled} -> {new_throttled}")
                    self.update_throttle_history(ip, new_throttled, server_name)

                    try:
                        if old_throttled is True and new_throttled is False:
                            self.enable_downloader(ip)
                        elif old_throttled is False and new_throttled is True:
                            self.disable_downloader(ip, url, username, password)
                    except Exception as e:
                        logger.error(f"[联动] {ip} 出错: {e}")

            self.cached_data = new_data
            logger.info(f"数据更新成功,共 {len(self.cached_data)} 台服务器")

        except Exception as e:
            logger.error(f"更新缓存数据失败: {e}")

    def data_collection_loop(self):
        """数据收集循环"""
        logger.info("数据收集线程已启动")
        self.update_cached_data()

        while True:
            try:
                time.sleep(300)
                self.update_cached_data()
            except Exception as e:
                logger.error(f"数据收集出错: {e}")
                time.sleep(60)

    def fetch_vertex_run_info(self) -> dict:
        """获取 Vertex 运行信息"""
        if not self.vertex_base_url or not self.vertex_cookie:
            return {"success": False, "error": "配置缺失"}

        try:
            api_url = f"{self.vertex_base_url}/api/setting/getRunInfo"
            headers = {"Cookie": self.vertex_cookie, "User-Agent": "Mozilla/5.0"}
            
            response = requests.get(api_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            return response.json()
        except Exception as e:
            logger.error(f"[Vertex] 获取运行信息失败: {e}")
            return {"success": False, "error": str(e)}

    def send_vertex_daily_report(self):
        """发送 Vertex 日报"""
        if not self.telegram_notifier:
            return

        try:
            run_info = self.fetch_vertex_run_info()
            
            if not run_info.get('success'):
                return

            self.telegram_notifier.send_vertex_report(run_info)
        except Exception as e:
            logger.error(f"发送日报失败: {e}")

    def run(self):
        """启动Flask应用"""
        logger.info(f"启动Web服务,端口: {self.port}")
        logger.info(f"监控面板: http://localhost:{self.port}/")
        self.app.run(host='0.0.0.0', port=self.port, debug=False)


def main():
    monitor = NetcupTrafficMonitor()
    monitor.run()


if __name__ == '__main__':
    main()