# 样本制作任务管理系统

面向多用户协作的多轮对话样本制作平台，支持任务领取、原始对话上传、自动质检评级、验收指标跟踪与交付物打包。

## 功能概览

- **任务池**：从 `questions_1200.json` 加载 1200 个预设多轮对话任务
- **领取/释放**：用户领取后独占任务，可主动释放；通过后不可再领
- **样本提交**：上传 OpenClaw `.jsonl` 原始文件，自动执行转换 → 质检 → 难度评级
- **验收看板**：实时展示已通过数、来源/模型/场景/难度分布
- **管理后台**：创建用户、导入题目、下载交付 ZIP（仅管理员）

第一期仅开放 **OpenClaw** 全流程，Hermes 上传入口已预留但暂不可用。

## 技术栈

- 后端：FastAPI + SQLAlchemy + MySQL + 现有 Python 流水线脚本
- 前端：React + Vite + Tailwind CSS v4
- 包管理：uv（Python）、npm（前端）

## Windows 开发环境

### 1. 安装依赖

```bash
# Python 依赖
uv sync

# 前端依赖
cd frontend
npm install
```

### 2. 配置环境变量

复制并编辑 `.env`：

```env
DB_HOST=...
DB_PORT=...
DB_USER=...
DB_PASSWORD=...
DB_NAME=...

SECRET_KEY=请替换为随机长字符串
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123

DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_API_BASE=https://api.deepseek.com

# 后端端口，默认 8000；若被占用可改为 8005
APP_PORT=8005
```

### 3. 启动服务

**终端 1 - 后端 API：**

```bash
uv run python server.py
```

**终端 2 - 前端开发服务器：**

```bash
cd frontend
npm run dev
```

浏览器访问：http://localhost:5173

默认管理员：`admin` / `admin123`（首次启动自动创建）

### 4. 生产构建（本地验证）

```bash
cd frontend
npm run build
```

构建产物输出到 `static/`，随后仅启动 `server.py` 即可同时提供 API 和前端页面。

## Linux 部署

### 1. 准备环境

```bash
# 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 克隆项目后
uv sync
cd frontend && npm install && npm run build && cd ..
```

### 2. 配置 `.env`

与开发环境相同，确保服务器可访问腾讯云 MySQL。

### 3. 使用 systemd 常驻运行（生产推荐）

前台 `uv run python server.py` 适合开发调试；**Ctrl+C 或断开 SSH 会停止服务**。生产环境请用 systemd。

**（1）确认前端已构建、`.env` 已配置**

```bash
cd /root/dialog_task_manager   # 换成你的实际目录
grep APP_PORT .env             # 例如 APP_PORT=8005
test -f static/index.html && echo "frontend OK" || (cd frontend && npm run build)
chmod +x deploy/start.sh
# 若从 Windows 拉取代码，先去掉 CRLF（exit 127 常见原因）
sed -i 's/\r$//' deploy/start.sh
```

**（2）安装 systemd 单元**

若项目不在 `/root/dialog_task_manager`，先改 `deploy/dialog-task-manager.service` 里的路径，再执行：

```bash
sudo cp deploy/dialog-task-manager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable dialog-task-manager
sudo systemctl start dialog-task-manager
sudo systemctl status dialog-task-manager
```

**（3）常用运维命令**

```bash
sudo systemctl stop dialog-task-manager       # 停止
sudo systemctl restart dialog-task-manager    # 重启（改 .env 后需执行）
journalctl -u dialog-task-manager -f          # 实时日志
journalctl -u dialog-task-manager -n 100      # 最近 100 行
```

**（4）更新代码后**

```bash
cd /root/dialog_task_manager
git pull origin main
uv sync
cd frontend && npm install && npm run build && cd ..
sudo systemctl restart dialog-task-manager
```

服务监听 `.env` 中的 `APP_PORT`（默认 8005），浏览器访问：`http://服务器IP:8005`。

> 若之前用前台方式启动过，先 `Ctrl+C` 或 `pkill -f "uvicorn backend.app:app"`，再 `systemctl start`，避免端口冲突。

**（5）故障排查（`status=127` / 反复 auto-restart）**

`exit-code 127` 表示「命令找不到」，按顺序执行：

```bash
cd /root/dialog_task_manager

# 1. 看 systemd 日志
journalctl -u dialog-task-manager -n 30 --no-pager

# 2. 检查脚本换行符（有 ^M 说明是 Windows CRLF，会导致 127）
cat -A deploy/start.sh | head -3
sed -i 's/\r$//' deploy/start.sh
chmod +x deploy/start.sh

# 3. 检查 Python 虚拟环境
ls -la .venv/bin/uvicorn || uv sync

# 4. 手动运行脚本（应看到 Uvicorn running on ...）
./deploy/start.sh

# 5. 确认无误后重启服务
sudo systemctl restart dialog-task-manager
sudo systemctl status dialog-task-manager
```

若 `.env` 中密码含 `&`、`$` 等特殊字符，请用引号包裹，例如：`DB_PASSWORD='slover_123&'`。

**`.env` 必须是 Unix 换行（LF）**。从 Windows 复制到 Linux 后若日志出现 `.env: line N: $'\r': command not found`：

```bash
sed -i 's/\r$//' .env
sed -i 's/\r$//' deploy/start.sh
sudo systemctl restart dialog-task-manager
```

### 4. Nginx 反向代理（可选）

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8005;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        client_max_body_size 100M;
    }
}
```

## 目录结构

```
make_sample_service/
├── backend/                 # FastAPI 后端
├── frontend/                # React 前端
├── data/
│   ├── uploads/             # 用户上传原始文件
│   ├── samples/             # 已通过样本汇总（交付目录）
│   └── backups/             # 已通过样本备份（只增不删）
├── static/                  # 前端构建产物
├── convert_openclaw.py      # 格式转换
├── quality_check.py         # 质检
├── batch_deepseek_simple.py # 难度评级
├── run_openclaw_pipeline.py # 命令行一键流水线
├── questions_1200.json      # 预设任务题库
├── server.py                # 服务入口
└── .env                     # 环境配置
```

## 样本处理流程

1. 用户在平台领取任务，按页面提示逐轮复制提问到 OpenClaw 对话
2. 导出 `.jsonl` 原始文件并上传，选择来源和模型版本
3. 系统自动执行：
   - `convert_openclaw.py` → `openclaw-待质检数据/`
   - `quality_check.py` → `openclaw-待质检数据-质检结果/`
   - `batch_deepseek_simple.py` → 各 session 下 `task_difficulty_justification.json`
4. 质检通过后样本入库至 `data/samples/`，并备份至 `data/backups/`
5. 管理员从后台下载 ZIP 交付包

## 命令行流水线（独立使用）

不通过 Web 平台时，仍可直接运行：

```bash
uv run python run_openclaw_pipeline.py --input_dir sample/openclaw
```

## API 说明

| 接口 | 说明 |
|------|------|
| `POST /api/auth/login` | 登录 |
| `GET /api/tasks` | 任务列表 |
| `POST /api/tasks/{id}/claim` | 领取任务 |
| `POST /api/tasks/{id}/release` | 释放任务 |
| `POST /api/tasks/{id}/upload` | 上传样本 |
| `GET /api/stats/dashboard` | 验收看板 |
| `POST /api/questions/import` | 导入增量题目（管理员） |
| `GET /api/delivery/zip` | 下载交付 ZIP（管理员） |

## 注意事项

- 已通过样本会同时写入 `data/samples/` 和 `data/backups/`，请勿手动删除
- DeepSeek API Key 统一由服务端 `.env` 管理，用户无需配置
- 质检失败可重复上传，任务仍归原领取人所有
- Hermes 流水线开发完成后，开放上传入口即可接入同一套流程
