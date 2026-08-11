import pytest

from habit_tracker.application.use_cases.create_habit import CreateHabit
from habit_tracker.application.use_cases.register_user import RegisterUser
from habit_tracker.application.use_cases.start_checkin import StartCheckin
from habit_tracker.domain.exceptions import UserNotFoundError
from habit_tracker.domain.value_objects import HabitName, TelegramId
from habit_tracker.domain.value_objects.frequency import Frequency
from tests.unit.conftest import (
    FakePatternAnalyzer,
    InMemoryCompletionRepository,
    InMemoryHabitRepository,
    InMemoryUserRepository,
)


class _CountingCompletionRepository:
    """Delegates to a real fake while tallying how often each method is called."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls: dict[str, int] = {}

    def __getattr__(self, name: str):
        attr = getattr(self._inner, name)

        async def counted(*args, **kwargs):
            self.calls[name] = self.calls.get(name, 0) + 1
            return await attr(*args, **kwargs)

        return counted


class _CapturingPatternAnalyzer:
    def __init__(self) -> None:
        self.completions: dict[str, list] | None = None

    async def analyze_patterns(self, user_id: int, completions: dict[str, list]) -> list:
        self.completions = completions
        return []

    async def generate_coaching_message(self, user_id: int, patterns: list, context: object) -> str:
        return "Keep going!"


@pytest.fixture
def deps():
    return (
        InMemoryUserRepository(),
        InMemoryHabitRepository(),
        InMemoryCompletionRepository(),
        FakePatternAnalyzer(),
    )


class TestStartCheckin:
    async def test_returns_pending_habits(self, deps):
        user_repo, habit_repo, comp_repo, analyzer = deps
        await RegisterUser(user_repo).execute(TelegramId(1))
        await CreateHabit(user_repo, habit_repo).execute(TelegramId(1), HabitName("gym"))
        await CreateHabit(user_repo, habit_repo).execute(TelegramId(1), HabitName("read"))

        uc = StartCheckin(user_repo, habit_repo, comp_repo, analyzer)
        result = await uc.execute(TelegramId(1))

        assert len(result.pending) == 2
        assert result.coaching == "Keep going!"

    async def test_returns_persistent_user_id_not_telegram_id(self, deps):
        """Memory insights are keyed on this ID, so it must not be the Telegram ID."""
        user_repo, habit_repo, comp_repo, analyzer = deps
        user, _ = await RegisterUser(user_repo).execute(TelegramId(555555))
        await CreateHabit(user_repo, habit_repo).execute(TelegramId(555555), HabitName("gym"))

        uc = StartCheckin(user_repo, habit_repo, comp_repo, analyzer)
        result = await uc.execute(TelegramId(555555))

        assert result.user_id == user.id
        assert result.user_id != 555555

    async def test_no_habits(self, deps):
        user_repo, habit_repo, comp_repo, analyzer = deps
        await RegisterUser(user_repo).execute(TelegramId(1))

        uc = StartCheckin(user_repo, habit_repo, comp_repo, analyzer)
        result = await uc.execute(TelegramId(1))

        assert len(result.pending) == 0
        assert "add_habit" in result.coaching.lower()

    async def test_user_not_found(self, deps):
        user_repo, habit_repo, comp_repo, analyzer = deps
        uc = StartCheckin(user_repo, habit_repo, comp_repo, analyzer)
        with pytest.raises(UserNotFoundError):
            await uc.execute(TelegramId(999))

    async def test_history_is_fetched_in_one_query_regardless_of_habit_count(self, deps):
        """Guards against reintroducing the per-habit loop this replaced."""
        user_repo, habit_repo, comp_repo, analyzer = deps
        comp_repo = _CountingCompletionRepository(comp_repo)
        await RegisterUser(user_repo).execute(TelegramId(1))
        for name in ("gym", "read", "walk", "meditate", "journal"):
            await CreateHabit(user_repo, habit_repo).execute(TelegramId(1), HabitName(name))

        await StartCheckin(user_repo, habit_repo, comp_repo, analyzer).execute(TelegramId(1))

        assert comp_repo.calls["find_by_habits_since"] == 1

    async def test_only_daily_habits_are_sent_for_weekday_pattern_analysis(self, deps):
        user_repo, habit_repo, comp_repo, _ = deps
        analyzer = _CapturingPatternAnalyzer()
        await RegisterUser(user_repo).execute(TelegramId(1))
        await CreateHabit(user_repo, habit_repo).execute(TelegramId(1), HabitName("run"), frequency=Frequency.DAILY)
        await CreateHabit(user_repo, habit_repo).execute(
            TelegramId(1),
            HabitName("weekly review"),
            frequency=Frequency.WEEKLY,
        )

        await StartCheckin(user_repo, habit_repo, comp_repo, analyzer).execute(TelegramId(1))

        assert analyzer.completions is not None
        assert set(analyzer.completions) == {"run"}
