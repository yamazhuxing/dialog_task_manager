#!/usr/bin/env python3
"""启动样本制作任务管理系统 API 服务。"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)
