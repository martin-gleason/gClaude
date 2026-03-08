import time

from src.chat.context import ThreadContextStore, Turn


class TestThreadContextStore:
    def test_new_store_is_empty(self):
        store = ThreadContextStore()
        assert store.get("any-thread") is None

    def test_add_turn_creates_context(self):
        store = ThreadContextStore()
        store.add_turn("thread-1", "What is VLOOKUP?", "VLOOKUP is...")
        ctx = store.get("thread-1")
        assert ctx is not None
        assert ctx.thread_name == "thread-1"
        assert len(ctx.turns) == 1
        assert ctx.turns[0].question == "What is VLOOKUP?"
        assert ctx.turns[0].answer == "VLOOKUP is..."

    def test_multiple_turns_in_same_thread(self):
        store = ThreadContextStore()
        store.add_turn("thread-1", "Q1", "A1")
        store.add_turn("thread-1", "Q2", "A2")
        ctx = store.get("thread-1")
        assert len(ctx.turns) == 2
        assert ctx.turns[0].question == "Q1"
        assert ctx.turns[1].question == "Q2"

    def test_separate_threads_independent(self):
        store = ThreadContextStore()
        store.add_turn("thread-1", "Q1", "A1")
        store.add_turn("thread-2", "Q2", "A2")
        ctx1 = store.get("thread-1")
        ctx2 = store.get("thread-2")
        assert len(ctx1.turns) == 1
        assert len(ctx2.turns) == 1
        assert ctx1.turns[0].question == "Q1"
        assert ctx2.turns[0].question == "Q2"

    def test_max_turns_evicts_oldest(self):
        store = ThreadContextStore(max_turns=3)
        store.add_turn("t", "Q1", "A1")
        store.add_turn("t", "Q2", "A2")
        store.add_turn("t", "Q3", "A3")
        store.add_turn("t", "Q4", "A4")
        ctx = store.get("t")
        assert len(ctx.turns) == 3
        assert ctx.turns[0].question == "Q2"
        assert ctx.turns[2].question == "Q4"

    def test_max_entries_evicts_oldest_thread(self):
        store = ThreadContextStore(max_entries=2)
        store.add_turn("thread-1", "Q1", "A1")
        store.add_turn("thread-2", "Q2", "A2")
        store.add_turn("thread-3", "Q3", "A3")
        assert store.get("thread-1") is None
        assert store.get("thread-2") is not None
        assert store.get("thread-3") is not None

    def test_ttl_expiry(self):
        store = ThreadContextStore(ttl_seconds=60)
        store.add_turn("thread-1", "Q1", "A1")
        # Backdate the created_at to simulate expiry
        ctx = store.get("thread-1")
        ctx.created_at = time.time() - 120
        assert store.get("thread-1") is None

    def test_get_history_returns_turns(self):
        store = ThreadContextStore()
        store.add_turn("t", "Q1", "A1")
        store.add_turn("t", "Q2", "A2")
        history = store.get_history("t")
        assert len(history) == 2
        assert isinstance(history[0], Turn)
        assert history[0].question == "Q1"
        assert history[1].answer == "A2"

    def test_get_history_empty_thread(self):
        store = ThreadContextStore()
        history = store.get_history("nonexistent")
        assert history == []

    def test_clear_empties_store(self):
        store = ThreadContextStore()
        store.add_turn("t1", "Q1", "A1")
        store.add_turn("t2", "Q2", "A2")
        store.clear()
        assert store.get("t1") is None
        assert store.get("t2") is None

    def test_set_spreadsheet_context(self):
        store = ThreadContextStore()
        store.add_turn("t", "Q1", "A1")
        store.set_spreadsheet_context("t", "Sheet1: col A, col B")
        ctx = store.get("t")
        assert ctx.spreadsheet_context == "Sheet1: col A, col B"

    def test_spreadsheet_context_persists_across_turns(self):
        store = ThreadContextStore()
        store.add_turn("t", "Q1", "A1")
        store.set_spreadsheet_context("t", "sheet data")
        store.add_turn("t", "Q2", "A2")
        ctx = store.get("t")
        assert ctx.spreadsheet_context == "sheet data"
        assert len(ctx.turns) == 2

    def test_set_spreadsheet_context_creates_entry_if_missing(self):
        store = ThreadContextStore()
        store.set_spreadsheet_context("new-thread", "sheet data")
        ctx = store.get("new-thread")
        assert ctx is not None
        assert ctx.spreadsheet_context == "sheet data"
        assert len(ctx.turns) == 0


class TestTurnTokenFields:
    def test_turn_has_token_fields_defaulting_zero(self):
        turn = Turn(question="Q", answer="A")
        assert turn.input_tokens == 0
        assert turn.output_tokens == 0

    def test_turn_accepts_token_values(self):
        turn = Turn(question="Q", answer="A", input_tokens=100, output_tokens=50)
        assert turn.input_tokens == 100
        assert turn.output_tokens == 50

    def test_existing_turn_creation_still_works(self):
        turn = Turn(question="Q1", answer="A1")
        assert turn.question == "Q1"
        assert turn.answer == "A1"


class TestThreadContextTokenTotals:
    def test_thread_context_has_token_totals(self):
        from src.chat.context import ThreadContext
        ctx = ThreadContext(thread_name="t1")
        assert ctx.total_input_tokens == 0
        assert ctx.total_output_tokens == 0

    def test_add_turn_with_tokens(self):
        store = ThreadContextStore()
        store.add_turn("t1", "Q1", "A1", input_tokens=100, output_tokens=50)
        ctx = store.get("t1")
        assert ctx.turns[0].input_tokens == 100
        assert ctx.turns[0].output_tokens == 50

    def test_add_turn_accumulates_thread_totals(self):
        store = ThreadContextStore()
        store.add_turn("t1", "Q1", "A1", input_tokens=100, output_tokens=50)
        store.add_turn("t1", "Q2", "A2", input_tokens=200, output_tokens=80)
        ctx = store.get("t1")
        assert ctx.total_input_tokens == 300
        assert ctx.total_output_tokens == 130
