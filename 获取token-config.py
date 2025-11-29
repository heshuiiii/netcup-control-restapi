import time
import json
import requests

AUTH_URL = "https://www.servercontrolpanel.de/realms/scp/protocol/openid-connect/auth/device"
TOKEN_URL = "https://www.servercontrolpanel.de/realms/scp/protocol/openid-connect/token"

# 这里放多个账号，每个账号只需要 client_id = "scp"
ACCOUNTS = [
    {"name": "331022", "client_id": "scp"},
    {"name": "331058", "client_id": "scp"},
    {"name": "331033", "client_id": "scp"},
    {"name": "331169", "client_id": "scp"}
]


def request_device_code(client_id):
    """请求 device_code、user_code、验证链接"""
    data = {
        "client_id": client_id,
        "scope": "offline_access openid"
    }
    r = requests.post(AUTH_URL, data=data)
    r.raise_for_status()
    return r.json()


def poll_token(client_id, device_code, interval):
    """轮询 token endpoint，直到授权成功"""
    print(f"[{client_id}] 开始轮询，每 {interval}s 查询一次…")
    while True:
        data = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
            "client_id": client_id
        }
        r = requests.post(TOKEN_URL, data=data)
        resp = r.json()

        # 授权未完成
        if resp.get("error") == "authorization_pending":
            print(f"[{client_id}] 等待授权...")
            time.sleep(interval)
            continue

        # 授权成功
        if "access_token" in resp:
            print(f"[{client_id}] 授权成功，获取到 access_token！")
            return resp

        # 授权过期
        if resp.get("error") == "expired_token":
            print(f"[{client_id}] device_code 已过期，请重新运行脚本。")
            return None

        # 其他错误
        print(f"[{client_id}] 遇到错误：{resp}")
        return None


def main():
    rest_accounts = []

    for acc in ACCOUNTS:
        name = acc["name"]
        client_id = acc["client_id"]

        print(f"\n====== 账号 {name} 获取 device_code ======")
        dev = request_device_code(client_id)

        device_code = dev["device_code"]
        user_code = dev["user_code"]
        verify_url = dev["verification_uri_complete"]
        interval = dev["interval"]

        print(f"[{name}] 请在浏览器打开以下链接完成授权：")
        print(f"    {verify_url}")
        print(f"[{name}] 用户代码：{user_code}")
        print()

        # 开始轮询 token
        token_data = poll_token(client_id, device_code, interval)

        if token_data:
            account_entry = {
                "account_id": name,
                "access_token": token_data.get("access_token", ""),
                "refresh_token": token_data.get("refresh_token", "")
            }
            rest_accounts.append(account_entry)

    # 构建最终的配置文件格式
    config = {
        "webhook_path": "/webhook/你的密钥",
        "port": 56578,
        "rest_accounts": rest_accounts,
        "vertex": {
            "base_url": "你的链接",
            "cookie": ""
        }
    }

    # 保存配置文件
    with open("tokens.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print("\n所有账号 token 获取完成，已保存到 tokens.json。")
    print(f"共获取 {len(rest_accounts)} 个账号的 token。")


if __name__ == "__main__":
    main()