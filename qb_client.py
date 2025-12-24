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
            self.client = Client(
                host=self.host, 
                username=self.username, 
                password=self.password, 
                VERIFY_WEBUI_CERTIFICATE=False
            )
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
    
    def reannounce_all(self):
        """
        强制所有种子向tracker汇报。
        """
        try:
            self.client.torrents.reannounce(hashes="all")
            logger.info("已发出强制汇报所有种子的指令。")
            # 等待一段时间让汇报完成
            time.sleep(2)
        except Exception as e:
            logger.error(f"强制汇报失败: {e}")
            
    def pause_all(self):
        """
        暂停所有种子任务，并检查是否全部暂停成功。
        """
        self.client.torrents.pause.all()
        logger.info("已发出暂停所有种子任务的指令。")
    
    def pause_all_with_reannounce(self):
        """
        先强制汇报，再暂停所有种子任务。
        """
        logger.info("开始执行：强制汇报 -> 暂停种子")
        
        # 1. 强制汇报
        self.reannounce_all()
        
        # 2. 暂停所有种子
        self.pause_all()
        
        logger.info("完成：种子已汇报并暂停")
            
    def delete_all(self, *, delete_files: bool = False) -> None:
        """
        删除全部任务。
        :param delete_files: True 时会连同本地数据一并删除（危险操作）
        """
        self.client.torrents.delete(hashes="all", delete_files=delete_files)
        logger.info("已发出删除全部任务的指令。")

    def resume_all(self):
        """恢复所有暂停的种子"""
        self.client.torrents.resume.all()
        logger.info("已发出恢复所有种子的指令。")

    def pause_and_delete_all(self, *, delete_files: bool = False) -> None:
        """
        先强制汇报，再暂停，最后删除所有任务。
        :param delete_files: True 时会连同本地数据一并删除（危险操作）
        """
        logger.info("开始执行：强制汇报 -> 暂停 -> 删除种子")
        
        # 1. 强制汇报
        self.reannounce_all()
        
        # 2. 暂停所有种子
        self.pause_all()
        
        # 3. 等待一下确保暂停完成
        time.sleep(1)
        
        # 4. 删除所有种子
        self.delete_all(delete_files=delete_files)
        
        logger.info("完成：种子已汇报、暂停并删除")

## 测试代码
#if __name__ == "__main__":
#    # 初始化客户端
#    qb_client = QBittorrentClient("185.244.194.39")
#    
#    qb_client.is_alive()
#    
#    # 使用新方法：先汇报再暂停再删除
#    qb_client.pause_and_delete_all(delete_files=False)