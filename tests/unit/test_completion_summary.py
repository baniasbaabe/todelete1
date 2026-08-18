from habit_tracker.domain.value_objects.completion_summary import CompletionSummary


class TestCompletionSummary:
    def test_all_completed(self):
        s = CompletionSummary(total=5, completed=5)
        assert s.pending == 0
        assert s.completion_rate == 100.0

    def test_none_completed(self):
        s = CompletionSummary(total=3, completed=0)
        assert s.pending == 3
        assert s.completion_rate == 0.0

    def test_partial(self):
        s = CompletionSummary(total=4, completed=3)
        assert s.pending == 1
        assert s.completion_rate == 75.0

    def test_empty(self):
        s = CompletionSummary(total=0, completed=0)
        assert s.completion_rate == 0.0

    def test_encouragement_excellent(self):
        s = CompletionSummary(total=5, completed=5)
        assert "crushing" in s.get_encouragement().lower() or "outstanding" in s.get_encouragement().lower()

    def test_encouragement_zero(self):
        s = CompletionSummary(total=5, completed=0)
        assert "tomorrow" in s.get_encouragement().lower() or "got this" in s.get_encouragement().lower()
