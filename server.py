#!/usr/bin/env python3
"""启动样本制作任务管理系统 API 服务。"""

import uvicorn

from backend.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "backend.app:app",
        host="0.0.0.0",
        port=settings.app_port,
        reload=True,
    )
