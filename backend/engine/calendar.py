"""Market calendar awareness.

Phase 2 ships WeekdayCalendar: Monday-Friday sessions minus an explicit
holiday set, with configurable session open/close (UTC) and per-date early
closes. This is deliberately simple and fully deterministic; a real
exchange-calendar backend (DST-aware NYSE, LSE, etc.) can implement the
same interface later. KNOWN LIMITATION: fixed UTC session times ignore US
daylight-saving shifts — documented, not hidden.

Convention used across the engine: a bar's `ts` is its CLOSE (completion)
time. A daily bar for session D therefore carries ts = session_close(D),
which is exactly what makes multi-timeframe availability checks correct.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from engine.data.schema_types import Timeframe


@dataclass(frozen=True, slots=True)
class WeekdayCalendar:
    holidays: frozenset[date] = field(default_factory=frozenset)
    open_time: time = time(14, 30)    # 09:30 ET in standard time, as UTC
    close_time: time = time(21, 0)    # 16:00 ET in standard time, as UTC
    early_closes: tuple[tuple[date, time], ...] = ()  # (date, close_time_utc)

    def _early(self) -> dict[date, time]:
        return dict(self.early_closes)

    def is_session(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def sessions(self, start: date, end: date) -> list[date]:
        out, d = [], start
        while d <= end:
            if self.is_session(d):
                out.append(d)
            d += timedelta(days=1)
        return out

    def session_open(self, d: date) -> datetime:
        return datetime.combine(d, self.open_time, tzinfo=UTC)

    def session_close(self, d: date) -> datetime:
        close = self._early().get(d, self.close_time)
        return datetime.combine(d, close, tzinfo=UTC)

    def expected_bar_times(self, d: date, timeframe: Timeframe) -> list[datetime]:
        """Completion timestamps of every bar expected in session d.
        Daily -> [session_close]. Intraday -> open+step, open+2*step, ...
        up to and including the (possibly early) close."""
        if not self.is_session(d):
            return []
        if timeframe is Timeframe.D1:
            return [self.session_close(d)]
        step = timeframe.delta
        t = self.session_open(d) + step
        close = self.session_close(d)
        out = []
        while t <= close:
            out.append(t)
            t += step
        return out
