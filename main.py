from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from database import async_session, engine
from models import Base, User
from crud import get_user_by_username
from schemas import UserCreate, UserLogin
from utils import get_password_hash, verify_password, create_access_token, SECRET_KEY, ALGORITHM
from utils import get_current_user, require_role
from sqlalchemy import select
from fastapi.staticfiles import StaticFiles
from config import settings
from prometheus_fastapi_instrumentator import Instrumentator
import schemas, models
from routes import notes, tasks, ws
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# ✅ Logging + Prometheus

from logging_config import configure_logging
from logging_middleware import LoggingMiddleware

import logging

print(settings.database_url)

# ✅ FastAPI init
app = FastAPI()

@app.get("/health")
async def healthcheck():
    return JSONResponse(content={"status": "ok"}, status_code=200)

# ✅ Logging config
configure_logging()
app.add_middleware(LoggingMiddleware)

# ✅ Prometheus
instrumentator = Instrumentator()
instrumentator.instrument(app).expose(app)

# ✅ Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# ✅ Routers
app.include_router(notes.router)
app.include_router(tasks.router)
app.include_router(ws.router)

# ✅ DB Init
@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# ✅ DB Dependency
async def get_db():
    async with async_session() as session:
        yield session

# ✅ Auth
@app.post("/register")
async def register(user: UserCreate, db: AsyncSession = Depends(get_db)):
    hashed_password = get_password_hash(user.password)
    new_user = User(username=user.username, hashed_password=hashed_password, role="user")
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    logging.info("New user registered", extra={"username": user.username})
    return new_user

@app.post("/login")
async def login(user: UserLogin, db: AsyncSession = Depends(get_db)):
    db_user = await get_user_by_username(db, user.username)
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        logging.warning("Login failed", extra={"username": user.username})
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = create_access_token(data={"sub": user.username})
    logging.info("User logged in", extra={"username": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

# ✅ User Info
from fastapi import APIRouter
router = APIRouter()

@router.get("/users/me", response_model=schemas.UserOut)
async def read_users_me(current_user: models.User = Depends(get_current_user)):
    return current_user

app.include_router(router)

# ✅ Admin view
@app.get("/admin/users")
async def get_all_users(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(require_role("admin"))
):
    result = await db.execute(select(models.User))
    users = result.scalars().all()
    return users
