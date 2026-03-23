from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Generator, Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine, desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session

# Load environment for SECRET_KEY and database path if provided
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))
MAX_PASSWORD_BYTES = int(os.getenv("MAX_PASSWORD_BYTES", "128"))

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto",
)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="user", nullable=False)
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, nullable=False, default="Untitled conversation")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship("User", back_populates="conversations")
    messages = relationship(
        "ConversationMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.created_at",
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    role = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    conversation = relationship("Conversation", back_populates="messages")


def create_db() -> None:
    Base.metadata.create_all(bind=engine)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    role: str = "user"


class UserLogin(BaseModel):
    username_or_email: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    email: EmailStr
    role: str

    class Config:
        from_attributes = True


class ConversationOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationMessageOut(BaseModel):
    id: int
    role: str
    kind: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    # pbkdf2_sha256 handles long inputs, but we cap to prevent abuse.
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Password too long; must be <= {MAX_PASSWORD_BYTES} bytes.",
        )
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_user_by_username_or_email(db: Session, username_or_email: str) -> Optional[User]:
    stmt = select(User).where((User.username == username_or_email) | (User.email == username_or_email))
    return db.execute(stmt).scalars().first()


def authenticate_user(db: Session, username_or_email: str, password: str) -> Optional[User]:
    user = get_user_by_username_or_email(db, username_or_email)
    if not user or not verify_password(password, user.password_hash):
        return None
    return user


async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = get_user_by_username_or_email(db, username)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user


def create_user(db: Session, user_in: UserCreate) -> User:
    new_user = User(
        username=user_in.username,
        email=user_in.email,
        password_hash=hash_password(user_in.password),
        role=user_in.role or "user",
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Username or email already registered")
    db.refresh(new_user)
    return new_user


def _derive_title(seed_text: str) -> str:
    cleaned = " ".join(seed_text.split()).strip()
    if not cleaned:
        return "Untitled conversation"
    return cleaned[:77] + "..." if len(cleaned) > 80 else cleaned


def create_conversation(db: Session, user: User, title: Optional[str] = None, seed_text: str = "") -> Conversation:
    conversation = Conversation(
        user_id=user.id,
        title=(title or "").strip() or _derive_title(seed_text),
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def touch_conversation(db: Session, conversation: Conversation) -> Conversation:
    conversation.updated_at = datetime.utcnow()
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def get_conversation_for_user(db: Session, user: User, conversation_id: int) -> Conversation:
    stmt = select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user.id)
    conversation = db.execute(stmt).scalars().first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def list_conversations(db: Session, user: User) -> list[Conversation]:
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(desc(Conversation.updated_at), desc(Conversation.created_at))
    )
    return list(db.execute(stmt).scalars().all())


def list_conversation_messages(db: Session, conversation: Conversation) -> list[ConversationMessage]:
    stmt = (
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.created_at, ConversationMessage.id)
    )
    return list(db.execute(stmt).scalars().all())


def append_conversation_message(
    db: Session,
    conversation: Conversation,
    role: str,
    kind: str,
    content: str,
) -> ConversationMessage:
    message = ConversationMessage(
        conversation_id=conversation.id,
        role=role,
        kind=kind,
        content=content,
    )
    db.add(message)
    conversation.updated_at = datetime.utcnow()
    db.add(conversation)
    db.commit()
    db.refresh(message)
    return message


def get_recent_user_memory(db: Session, user: User, limit: int = 8) -> list[dict[str, Any]]:
    stmt = (
        select(ConversationMessage, Conversation.title)
        .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
        .where(Conversation.user_id == user.id)
        .order_by(desc(ConversationMessage.created_at), desc(ConversationMessage.id))
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    memory: list[dict[str, Any]] = []
    for message, title in reversed(rows):
        memory.append(
            {
                "conversation_title": title,
                "role": message.role,
                "kind": message.kind,
                "content": message.content,
                "created_at": message.created_at.isoformat() if message.created_at else None,
            }
        )
    return memory
