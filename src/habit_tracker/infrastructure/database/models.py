from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    habits: Mapped[list[HabitModel]] = relationship("HabitModel", back_populates="user")


ACTIVE_HABIT_NAME_INDEX = "uq_habits_user_id_active_name"


class HabitModel(Base):
    __tablename__ = "habits"
    __table_args__ = (
        Index("ix_habits_user_id_is_active", "user_id", "is_active"),
        # Partial rather than a plain UniqueConstraint: deletion is a soft
        # delete, so inactive rows keep their name and must not reserve it
        # forever. Without this, the check in CreateHabit is the only guard and
        # it is not atomic with the insert.
        Index(
            ACTIVE_HABIT_NAME_INDEX,
            "user_id",
            "name",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    frequency: Mapped[str] = mapped_column(String(50), nullable=False)
    verification_policy: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[UserModel] = relationship("UserModel", back_populates="habits")
    completions: Mapped[list[CompletionModel]] = relationship("CompletionModel", back_populates="habit")


class CompletionModel(Base):
    __tablename__ = "completions"
    __table_args__ = (Index("ix_completions_habit_id_completed_at", "habit_id", "completed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    habit_id: Mapped[int] = mapped_column(Integer, ForeignKey("habits.id", ondelete="CASCADE"), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    proof_type: Mapped[str] = mapped_column(String(50), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    verification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    habit: Mapped[HabitModel] = relationship("HabitModel", back_populates="completions")
