# Netcup Control REST API


这是基于 Flask 的 Netcup 控制接口监控程序，使用 Docker Compose 部署  或者python直接克隆运行。  
**注意**：程序依赖两个配置文件，需要你自行编辑：
- `config.json` （API 配置示例已提供）
- `dashboard.html` （界面模板）

---

# docker compose 已构建版本部署参考 
```https://hub.docker.com/r/aksviolet/netcup-control-restapi```

构建 ```docker build -t netcup-control-restapi .```



```docker compose up -d```

```
services:
  netcupcontrol-restapi:
    image: netcup-control-restapi:latest
    container_name: netcupcontrol-restapi
    ports:
      - "56578:56578"     
    volumes:
      - ./netcup-control-RESTAPI/config.json:/app/config.json
      - ./netcup-control-RESTAPI/dashboard.html:/app/dashboard.html
    restart: unless-stopped
```


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
  "webhook_path": "/webhook/密钥字符请修改",
  "port": 56666,
  "rest_accounts": [
  {
    "account_id": "327110",
    "access_token": "",
    "refresh_token": ""
  }

],
  "vertex": {
    "base_url": "https://vertex.example.com/api/v1",
    "cookie": ""
  },
  "telegram": {
    "bot_token": "你的bot_token请修改",
    "chat_id": "你的chat_id请修改"
  },
  "throttle_action": {
    "strategy": "pause_resume", #这里代表执行操作是 pause_resume pause delete   字面意思就是限速后暂停汇报 暂停汇报然后恢复后继续 直接删除
    "delete_files": true  #仅delete时生效
  }
}
