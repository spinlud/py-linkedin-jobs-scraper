import threading


# The floor of a floor: a run is never allowed to ask faster than this, whatever the pacer
# is doing. It also removes the degenerate configuration - a slow_mo of 0 gave a ceiling of
# min(PACING_CEILING_LIMIT, 0) = 0, so adaptation was silently inert - and it guarantees an
# enabled pacer always has somewhere to go, since the ceiling can then never be below 2s.
MIN_SLOW_MO = 0.2

# The pace rises at most to `slow_mo * PACING_CEILING_FACTOR`, and never past
# PACING_CEILING_LIMIT seconds however patient the caller asked to be: past that a run is
# not recovering from throttling, it is hanging on it.
PACING_CEILING_LIMIT = 10
PACING_CEILING_FACTOR = 10

# A 429 doubles the pace. Backing off hard costs seconds, where being throttled again costs
# a whole backoff ladder and the page that provoked it.
PACING_INCREASE_FACTOR = 2

# Easing is deliberately slower than raising, and it has to be earned by a run of work that
# nobody refused. LinkedIn's limit looks cumulative, so a run that has just been told to slow
# down should be reluctant to spend the recovery that buys it.
PACING_EASE_FACTOR = 1.5
CLEAN_RUN_BEFORE_EASING = 20


class Pacer:
    """The delay every sleep site of a run reads, moved by what LinkedIn answers.

    `slow_mo` is the floor and never the value: a pace that is comfortable for 25 jobs is not
    comfortable for 200, and one safe for 200 wastes minutes on a run of 25. The number a run
    should sleep is therefore not knowable before it starts, only discoverable while it runs.

    One instance serves a whole `LinkedinScraper`, so it is shared by every query thread and
    locked accordingly: the limit is enforced per account, which makes a 429 seen by one
    worker a reason for all of them to slow down.

    A pacer whose ceiling equals its floor is inert - `min(delay * factor, ceiling)` cannot
    move - which is what an opted out caller gets, at no cost to the sleep sites, which go on
    reading the same attribute either way.
    """

    def __init__(self, floor: float, ceiling: float):
        if ceiling < floor:
            raise ValueError('A pacer cannot have a ceiling below its floor')

        self._floor = floor
        self._ceiling = ceiling
        self._delay = floor
        self._clean_streak = 0
        self._throttled_count = 0
        self._lock = threading.Lock()

    @property
    def delay(self) -> float:
        """
        Return how long to sleep, now
        :return: float
        """

        with self._lock:
            return self._delay

    @property
    def throttled_count(self) -> int:
        """
        Return how many refusals have been reported to this pacer
        :return: int
        """

        with self._lock:
            return self._throttled_count

    def throttled(self) -> float:
        """
        Report a 429 and slow the run down

        Counting happens whether or not the pace can move, so the number stays meaningful for
        the metrics of a run that opted out of adapting.

        :return: float the new delay
        """

        with self._lock:
            self._throttled_count += 1
            self._clean_streak = 0
            self._delay = min(self._delay * PACING_INCREASE_FACTOR, self._ceiling)

            return self._delay

    def clean(self) -> float:
        """
        Report one unit of work nobody refused, easing the pace once enough have gone through
        :return: float the new delay
        """

        with self._lock:
            self._clean_streak += 1

            if self._clean_streak < CLEAN_RUN_BEFORE_EASING:
                return self._delay

            self._clean_streak = 0
            self._delay = max(self._delay / PACING_EASE_FACTOR, self._floor)

            return self._delay
