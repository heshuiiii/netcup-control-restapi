# Netcup Control REST API


这是基于 Flask 的 Netcup 控制接口监控程序，使用 Docker Compose 部署。  
**注意**：程序依赖两个配置文件，需要你自行编辑：
- `config.json` （API 配置示例已提供）
- `dashboard.html` （界面模板）

---
## 自行构建部署 首先首先
```git clone https://github.com/heshuiiii/netcup-control-restapi.git && cd netcup-control-restapi```


## docker compose 已构建版本部署参考 
```https://hub.docker.com/r/aksviolet/netcup-control-restapi```

### 暂停种子版本 限速后只暂停种子 设定好vt的分类删种或者保留  恢复限速后会继续下载上传种子    
**aksviolet/netcup-control-restapi:pauseresume**



## Vertex定时报送tracker数据 **http://ip:port/api/vertex/report**   访问会立即生成报告发送到telegram 




## 开始 

先获取各token   **access_token** **refresh_token**  


先修改```gen-token-config.py```如果你有多个scp服务器需要使用请填写如下，显示出的网址点开后输入对应scp账户和密码脚本自动填写如config.json
```
ACCOUNTS = [
    {"name": "331022", "client_id": "scp"},
    {"name": "331058", "client_id": "scp"},
    {"name": "331033", "client_id": "scp"},
    {"name": "331169", "client_id": "scp"}
]
```

在本地或者任意服务器运行脚本  ```获取token-config.py```    运行完毕后将  config.json配置补全


```
{
    "webhook_path": "/webhook/secret-密钥",
    "port": 56578,
    "rest_accounts": rest_accounts,
    "vertex": {
        "base_url": "https://vertex.example.com",
        "cookie": "YOUR_VERTEX_COOKIE_HERE"
    },
    "telegram": {
        "bot_token": "YOUR_TELEGRAM_BOT_TOKEN_HERE",
        "chat_id": "YOUR_TELEGRAM_CHAT_ID_HERE"
    }
}

```

构建 ```docker build -t netcup-control-restapi .```



```docker compose up -d```

```
services:
  netcupcontrol-restapi:
    image: netcup-control-restapi:pauseresume
    container_name: netcupcontrol-restapi
    ports:
      - "56578:56578"     
    volumes:
      - ./netcup-control-RESTAPI/config.json:/app/config.json
      - ./netcup-control-RESTAPI/dashboard.html:/app/dashboard.html
    restart: unless-stopped
```
