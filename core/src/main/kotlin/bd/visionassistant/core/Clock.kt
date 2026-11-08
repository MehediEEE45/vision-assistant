package bd.visionassistant.core

/**
 * Injected so the arbiter's TTL expiry, busy-window and latency budgets can be
 * tested without sleeping. Production uses [SystemClock]; tests drive time by
 * hand.
 */
fun interface Clock {
    /** Monotonic milliseconds. Must not go backwards across a wall-clock change. */
    fun nowMillis(): Long
}

object SystemClock : Clock {
    override fun nowMillis(): Long = System.nanoTime() / 1_000_000
}

class FakeClock(private var now: Long = 0L) : Clock {
    override fun nowMillis(): Long = now
    fun advance(millis: Long) { now += millis }
    fun set(millis: Long) { now = millis }
}
