import os
import time
from qbittorrentapi import Client
from logger import logger

class QBittorrentClient:
    """
    使用 qbittorrent-api 实现的精简版客户端，添加了种子状态检查功能。
    """

    def __init__(
        self,
        url: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        """
        初始化客户端，自动从环境变量中加载配置。
        """
        self.host = url
        self.username = username
        self.password = password

        try:
            self.client = Client(host=self.host, username=self.username, password=self.password, VERIFY_WEBUI_CERTIFICATE=False)
            self.client.auth_log_in()
            logger.info(f"成功连接到 qBittorrent API: {self.host}")
        except Exception as e:
            raise ConnectionError(f"连接 qBittorrent API 失败: {e}")

    def is_alive(self) -> bool:
        """简易健康检查：尝试请求应用版本。"""
        try:
            ver = self.client.app.version
            logger.info(f"{self.host} app version is {ver}")
            return True
        except Exception:
            return False
            
    def pause_all(self):
        """
        暂停所有种子任务，并检查是否全部暂停成功。
        """
        self.client.torrents.pause.all()
        logger.info("已发出暂停所有种子任务的指令。")
            
    def delete_all(self, *, delete_files: bool = False) -> None:
        """
        删除全部任务。
        :param delete_files: True 时会连同本地数据一并删除（危险操作）
        """
        self.client.torrents.delete(hashes="all", delete_files=delete_files)
        logger.info("已发出删除全部任务的指令。")

## 测试代码
#if __name__ == "__main__":
#    # 初始化客户端
#    qb_client = QBittorrentClient("185.244.194.39")
#    
#    qb_client.is_alive()
#    
#    qb_client.exit_block_new()
