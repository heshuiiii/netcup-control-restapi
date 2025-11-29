# Netcup Control REST API

这是基于 Flask 的 Netcup 控制接口监控程序，使用 Docker Compose 部署。  
**注意**：程序依赖两个配置文件，需要你自行编辑：
- `config.json` （API 配置示例已提供）
- `dashboard.html` （界面模板）

---

## 📂 文件说明

- `docker-compose.yml` - Docker Compose 配置
- `Dockerfile` - 构建镜像文件
- `netcup_monitor.py` - Flask 程序主入口
- `requirements.txt` - Python 依赖
- `config.json` - 用户配置文件（示例在 GitHub）
- `dashboard.html` - 页面模板（示例在 GitHub）

---

## 🔧 使用方法

### 1. 克隆仓库

```bash
git clone https://github.com/<你的用户名>/<你的仓库>.git
cd <你的仓库>
