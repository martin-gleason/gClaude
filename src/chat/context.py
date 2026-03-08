import time
from collections import OrderedDict
from dataclasses import dataclass, field


@dataclass
class Turn:
    question: str
    answer: str
    timestamp: float = field(default_factory=time.time)
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ThreadContext:
    thread_name: str
    turns: list[Turn] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    spreadsheet_context: str | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0


class ThreadContextStore:
    """In-memory thread context store with TTL eviction and LRU capacity limit.

    Note: Thread context is lost on restart/redeploy. Acceptable for MVP.
    """

    def __init__(
        self,
        max_entries: int = 500,
        ttl_seconds: int = 3600,
        max_turns: int = 10,
    ):
        self._store: OrderedDict[str, ThreadContext] = OrderedDict()
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._max_turns = max_turns

    def get(self, thread_name: str) -> ThreadContext | None:
        self._evict_expired()
        return self._store.get(thread_name)

    def add_turn(
        self,
        thread_name: str,
        question: str,
        answer: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        self._evict_expired()
        if thread_name not in self._store:
            self._store[thread_name] = ThreadContext(thread_name=thread_name)
        ctx = self._store[thread_name]
        ctx.turns.append(Turn(
            question=question,
            answer=answer,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ))
        ctx.total_input_tokens += input_tokens
        ctx.total_output_tokens += output_tokens
        if len(ctx.turns) > self._max_turns:
            ctx.turns = ctx.turns[-self._max_turns :]
        # Move to end for LRU ordering
        self._store.move_to_end(thread_name)
        # Enforce max entries (evict oldest)
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)

    def set_spreadsheet_context(self, thread_name: str, context: str) -> None:
        if thread_name not in self._store:
            self._store[thread_name] = ThreadContext(thread_name=thread_name)
        self._store[thread_name].spreadsheet_context = context

    def get_history(self, thread_name: str) -> list[Turn]:
        ctx = self.get(thread_name)
        if ctx is None:
            return []
        return list(ctx.turns)

    def _evict_expired(self) -> None:
        now = time.time()
        expired = []
        for name, ctx in self._store.items():
            if now - ctx.created_at > self._ttl_seconds:
                expired.append(name)
            else:
                break  # OrderedDict is ordered by insertion; older entries first
        for name in expired:
            del self._store[name]

    def clear(self) -> None:
        self._store.clear()
