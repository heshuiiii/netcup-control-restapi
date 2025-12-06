#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 通知模块
用于发送 Vertex 运行信息统计
"""

import requests
from logger import logger


class TelegramNotifier:
    """Telegram 通知器"""

    def __init__(self, bot_token: str, chat_id: str):
        """
        初始化 Telegram 通知器
        
        Args:
            bot_token: Telegram Bot Token
            chat_id: 目标 Chat ID
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        发送消息到 Telegram
        
        Args:
            text: 消息文本
            parse_mode: 解析模式 (HTML/Markdown)
            
        Returns:
            bool: 是否发送成功
        """
        try:
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }
            
            response = requests.post(self.api_url, json=payload, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            if result.get("ok"):
                logger.info(f"[Telegram] 消息发送成功")
                return True
            else:
                logger.error(f"[Telegram] 消息发送失败: {result}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"[Telegram] 发送消息时网络错误: {e}")
            return False
        except Exception as e:
            logger.error(f"[Telegram] 发送消息时发生错误: {e}")
            return False

    @staticmethod
    def bytes_to_tib(bytes_value: int) -> float:
        """
        将字节转换为 TiB
        
        Args:
            bytes_value: 字节数
            
        Returns:
            float: TiB 值
        """
        return bytes_value / (1024 ** 4)

    @staticmethod
    def format_ratio(uploaded: int, downloaded: int) -> str:
        """
        计算并格式化分享率
        
        Args:
            uploaded: 上传量(字节)
            downloaded: 下载量(字节)
            
        Returns:
            str: 格式化的分享率
        """
        if downloaded == 0:
            return "∞"
        ratio = uploaded / downloaded
        return f"{ratio:.3f}"

    def format_vertex_report(self, data: dict) -> str:
        """
        格式化 Vertex 运行报告
        
        Args:
            data: API 返回的数据
            
        Returns:
            str: 格式化的 HTML 消息
        """
        try:
            # 今日统计
            uploaded_today = data.get('uploadedToday', 0)
            downloaded_today = data.get('downloadedToday', 0)
            uploaded_today_tib = self.bytes_to_tib(uploaded_today)
            downloaded_today_tib = self.bytes_to_tib(downloaded_today)
            ratio_today = self.format_ratio(uploaded_today, downloaded_today)

            # 总计统计
            uploaded_total = data.get('uploaded', 0)
            downloaded_total = data.get('downloaded', 0)
            uploaded_total_tib = self.bytes_to_tib(uploaded_total)
            downloaded_total_tib = self.bytes_to_tib(downloaded_total)
            ratio_total = self.format_ratio(uploaded_total, downloaded_total)

            # 任务统计
            add_today = data.get('addCountToday', 0)
            reject_today = data.get('rejectCountToday', 0)
            delete_today = data.get('deleteCountToday', 0)

            # 构建消息
            message = f"""<b>📊 Vertex 今日运行报告</b>

<b>📈 今日流量统计</b>
• 上传: <code>{uploaded_today_tib:.3f} TiB</code>
• 下载: <code>{downloaded_today_tib:.3f} TiB</code>
• 分享率: <code>{ratio_today}</code>

<b>📦 今日任务统计</b>
• 新增: <code>{add_today}</code> 个
• 拒绝: <code>{reject_today}</code> 个
• 删除: <code>{delete_today}</code> 个

<b>💾 总计流量统计</b>
• 上传: <code>{uploaded_total_tib:.3f} TiB</code>
• 下载: <code>{downloaded_total_tib:.3f} TiB</code>
• 分享率: <code>{ratio_total}</code>
"""

            # 添加 Tracker 统计 (前10个,按上传量排序)
            per_tracker_today = data.get('perTrackerToday', [])
            if per_tracker_today:
                # 按上传量从高到低排序
                sorted_trackers = sorted(
                    per_tracker_today, 
                    key=lambda x: x.get('uploaded', 0), 
                    reverse=True
                )
                
                message += "\n<b>🎯 今日 Tracker Top 10 (按上传量排序)</b>\n"
                
                for idx, tracker in enumerate(sorted_trackers[:10], 1):
                    tracker_name = tracker.get('tracker', 'Unknown')
                    tracker_up = tracker.get('uploaded', 0)
                    tracker_down = tracker.get('downloaded', 0)
                    tracker_up_tib = self.bytes_to_tib(tracker_up)
                    tracker_down_tib = self.bytes_to_tib(tracker_down)
                    tracker_ratio = self.format_ratio(tracker_up, tracker_down)
                    
                    message += f"\n<b>{idx}. {tracker_name}</b>\n"
                    message += f"   ↑ <code>{tracker_up_tib:.3f} TiB</code> | "
                    message += f"↓ <code>{tracker_down_tib:.3f} TiB</code> | "
                    message += f"比率 <code>{tracker_ratio}</code>\n"

            message += f"\n<i>⏰ 统计时间: {self._get_current_time()}</i>"
            
            return message
            
        except Exception as e:
            logger.error(f"[Telegram] 格式化报告时发生错误: {e}")
            return f"<b>❌ 生成报告失败</b>\n\n错误: {str(e)}"

    @staticmethod
    def _get_current_time() -> str:
        """获取当前时间字符串"""
        from datetime import datetime
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def send_vertex_report(self, api_data: dict) -> bool:
        """
        发送 Vertex 运行报告
        
        Args:
            api_data: API 返回的数据字典
            
        Returns:
            bool: 是否发送成功
        """
        if not api_data.get('success'):
            logger.error("[Telegram] API 数据返回失败,无法生成报告")
            return False
        
        data = api_data.get('data', {})
        message = self.format_vertex_report(data)
        return self.send_message(message)
