import asynciofrom aiogram.client.default import DefaultBotProperties
import loggingfrom aiogram.client.default import DefaultBotProperties
import osfrom aiogram.client.default import DefaultBotProperties
from aiohttp import web
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, select
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

logging.basicConfig(level=logging.INFO)

# ─── 1. BAZA VA MODELLAR SOZLAMASI ───
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")  # <─── MANA SHU QATORNI QAYTA QO'SHAMIZ

if DATABASE_URL:
    if DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "?" in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.split("?")[0]

engine = create_async_engine(DATABASE_URL, echo=False, connect_args={"ssl": True})
# SSL ulanishni to'g'ridan-to'g'ri connect_args orqali xavfsiz yoqamiz
engine = create_async_engine(DATABASE_URL, echo=False, connect_args={"ssl": True})

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    xp = Column(Integer, default=0)
    level = Column(Integer, default=1)
    streak = Column(Integer, default=0)
    tasks = relationship("Task", back_populates="user", cascade="all, delete-orphan")

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    priority = Column(String, default="Medium")
    is_completed = Column(Boolean, default=False)
    user = relationship("User", back_populates="tasks")

# ─── 2. SPREAD / STATES ───
class TaskCreationForm(StatesGroup):
    waiting_for_title = State()
    waiting_for_priority = State()

# ─── 3. DIZAYN VA TUGMALAR ───
LOGO = "🚀 <b>SkyPortX</b>\n"
DIVIDER = "────────────────────────"

def generate_progress_bar(current: int, total: int, length: int = 10) -> str:
    if total <= 0: return "[░░░░░░░░░░] 0%"
    progress = min(current / total, 1.0)
    filled_length = int(length * progress)
    return f"[{'▓' * filled_length}{'░' * (length - filled_length)}] {int(progress * 100)}% ({current}/{total} XP)"

def get_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Planner (Reja)", callback_data="menu_planner")]
    ])

def get_planner_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Vazifa qo'shish", callback_data="task_add")],
        [InlineKeyboardButton(text="📋 Vazifalarni ko'rish", callback_data="tasks_view")],
        [InlineKeyboardButton(text="⬅️ Ortga", callback_data="menu_back")]
    ])

def get_priority_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 High (Muhim)", callback_data="priority_High")],
        [InlineKeyboardButton(text="🟡 Medium (O'rtacha)", callback_data="priority_Medium")],
        [InlineKeyboardButton(text="🟢 Low (Past)", callback_data="priority_Low")]
    ])

# ─── 4. BOT BUYRUQLARI (HANDLERS) ───
router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message):
    async with AsyncSessionLocal() as session:
        stmt = select(User).where(User.telegram_id == message.from_user.id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=message.from_user.id, username=message.from_user.username, full_name=message.from_user.full_name)
            session.add(user)
            await session.commit()
            await session.refresh(user)
    p_bar = generate_progress_bar(user.xp, 1000)
    welcome_text = f"{LOGO}{DIVIDER}\nXush kelibsiz, <b>{user.full_name}</b>!\n\n⚡ <b>Status:</b>\n├ <b>Level:</b> {user.level}\n└ <b>Streak:</b> 🔥 {user.streak} kun\n\n📊 <b>Progress:</b>\n{p_bar}\n{DIVIDER}"
    await message.answer(text=welcome_text, reply_markup=get_main_menu())

@router.callback_query(F.data == "menu_planner")
async def show_planner(callback: CallbackQuery):
    await callback.message.edit_text(text=f"{LOGO}{DIVIDER}\n📅 <b>Planner Bo'limi</b>\n\nKunlik vazifalaringizni shu yerda boshqaring.", reply_markup=get_planner_menu())

@router.callback_query(F.data == "menu_back")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text(text=f"{LOGO}{DIVIDER}\nAsosiy menyuga qaytdingiz.", reply_markup=get_main_menu())

@router.callback_query(F.data == "task_add")
async def add_task_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📝 Yangi vazifa nomini kiriting:")
    await state.set_state(TaskCreationForm.waiting_for_title)

@router.message(TaskCreationForm.waiting_for_title)
async def process_task_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("🟢 Vazifa ustuvorligini tanlang:", reply_markup=get_priority_keyboard())
    await state.set_state(TaskCreationForm.waiting_for_priority)

@router.callback_query(TaskCreationForm.waiting_for_priority, F.data.startswith("priority_"))
async def process_task_priority(callback: CallbackQuery, state: FSMContext):
    priority = callback.data.split("_")[1]
    data = await state.get_data()
    title = data.get("title")
    async with AsyncSessionLocal() as session:
        stmt = select(User).where(User.telegram_id == callback.from_user.id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            new_task = Task(user_id=user.id, title=title, priority=priority)
            session.add(new_task)
            await session.commit()
    await state.clear()
    await callback.message.edit_text(text=f"✅ Vazifa qo'shildi!\n\n📌 <b>{title}</b> [{priority}]", reply_markup=get_planner_menu())

@router.callback_query(F.data == "tasks_view")
async def view_tasks(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        stmt = select(Task).join(User).where(User.telegram_id == callback.from_user.id)
        result = await session.execute(stmt)
        tasks = result.scalars().all()
    if not tasks:
        text = f"{LOGO}{DIVIDER}\n📋 Hozircha vazifa yo'q."
    else:
        text = f"{LOGO}{DIVIDER}\n📋 <b>Vazifalaringiz:</b>\n\n"
        for idx, task in enumerate(tasks, 1):
            text += f"{idx}. {'✅' if task.is_completed else '⏳'} <b>{task.title}</b> [{task.priority}]\n"
    await callback.message.edit_text(text=text, reply_markup=get_planner_menu())

# ─── 5. RENDER SERVER PORT BINDING ───
async def handle(request): return web.Response(text="SkyPortX is active!")
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 8000))).start()

# ─── 6. ISHGA TUSHIRISH ───
async def main():
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    await start_web_server()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
