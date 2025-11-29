# Netcup Control REST API

这是基于 Flask 的 Netcup 控制接口监控程序，使用 Docker Compose 部署。  
**注意**：程序依赖两个配置文件，需要你自行编辑：
- `config.json` （API 配置示例已提供）
- `dashboard.html` （界面模板）

---


## 开始 

先获取各token   **access_token** **refresh_token**  


先修改```获取token-config.py```如果你有多个scp服务器需要使用请填写如下，显示出的网址点开后输入对应scp账户和密码脚本自动填写如config.json
```
ACCOUNTS = [
    {"name": "331022", "client_id": "scp"},
    {"name": "331058", "client_id": "scp"},
    {"name": "331033", "client_id": "scp"},
    {"name": "331169", "client_id": "scp"}
]
```

在本地或者任意服务器运行脚本  ```获取token-config.py```  


```
{
  "webhook_path": "/webhook/xxxxxxx",
  "port": 56578,
  "rest_accounts": [
  {
    "account_id": "327210",
    "access_token": "",
    "refresh_token": ""
  }
],
  "vertex": {
    "base_url": "",
    "cookie": ""
  }
}

```





