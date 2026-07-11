import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from backend.auth import hash_password
from backend.config import get_settings
from backend.database import Base, SessionLocal, engine
from backend.models import Task, User
from backend.routers.api import router as api_router
from backend.routers.auth import router as auth_router
from backend.services.questions import import_questions_from_data, load_questions_file

logger = logging.getLogger(__name__)


def _ensure_admin_and_questions() -> None:
    settings = get_settings()
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == settings.admin_username).first()
        if not admin:
            admin = User(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                role="admin",
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)
            logger.info("Created default admin user: %s", settings.admin_username)

        task_count = db.query(Task).count()
        if task_count == 0 and settings.questions_path.exists():
            questions = load_questions_file(settings.questions_path)
            imported, skipped = import_questions_from_data(
                db,
                questions,
                filename=settings.questions_path.name,
                imported_by=admin,
                import_batch="bootstrap",
            )
            logger.info("Bootstrapped questions: imported=%s skipped=%s", imported, skipped)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    for path in (
        settings.data_dir,
        settings.uploads_dir,
        settings.samples_dir,
        settings.backups_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
    _ensure_admin_and_questions()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="样本制作任务管理系统", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router, prefix="/api")
    app.include_router(api_router)

    static_dir = settings.project_root / "static"
    if static_dir.exists():
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            if full_path.startswith("api/"):
                return {"detail": "Not Found"}
            index = static_dir / "index.html"
            if index.exists():
                return FileResponse(index)
            return {"detail": "Frontend not built"}

    return app


app = create_app()
