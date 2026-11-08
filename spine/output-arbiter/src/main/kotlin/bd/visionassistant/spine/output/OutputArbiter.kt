package bd.visionassistant.spine.output

import bd.visionassistant.core.Announcement
import bd.visionassistant.core.Clock
import bd.visionassistant.core.DropReason
import bd.visionassistant.core.Priority
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.launch

/**
 * The single point at which this application decides what the user hears.
 *
 * Architectural rule #1: no feature ever speaks or vibrates directly. Features
 * submit an [Announcement] with a priority and a time-to-live, and this class
 * alone decides what is heard, what is deferred, what is dropped, and what is
 * resumed afterwards. Without it, a hazard warning, a turn instruction and a
 * book paragraph collide into noise and the user stops trusting the device —
 * an unrecoverable failure that no amount of later polish fixes.
 *
 * Architectural rule #2: haptics lead, speech explains. A hazard's vibration is
 * fired synchronously inside [submit], before this class touches a queue or a
 * coroutine, because a buzz reaches the user's motor response roughly 1.3
 * seconds before the sentence describing the danger finishes.
 *
 * All state lives on a single command loop, so there are no locks and the order
 * of submissions is the order of decisions.
 */
class OutputArbiter(
    private val speech: SpeechEngine,
    private val haptics: HapticEngine,
    private val earcons: EarconEngine,
    private val clock: Clock,
    scope: CoroutineScope,
) {
    private val commands = Channel<Command>(Channel.UNLIMITED)

    // DROP_OLDEST, and never emitted with a suspending call. Events are
    // telemetry; a slow or absent observer must not be able to stall the loop
    // that decides whether a hazard warning is heard.
    private val _events = MutableSharedFlow<ArbiterEvent>(
        replay = 0,
        extraBufferCapacity = 128,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    val events: SharedFlow<ArbiterEvent> = _events

    private val queue = ArrayDeque<Pending>()
    private var current: Active? = null
    private var suspendedLongform: Suspended? = null
    private var busySinceMillis: Long? = null
    private var sequence: Long = 0

    init {
        scope.launch {
            for (command in commands) handle(command, scope)
        }
    }

    // -- public API ----------------------------------------------------------

    /**
     * Non-blocking. Safe to call from a sensor callback: the only work done on
     * the caller's thread is the hazard haptic, which is the one thing that
     * cannot afford to wait for a dispatcher.
     */
    fun submit(announcement: Announcement) {
        var hapticAlreadyFired = false
        if (announcement.priority == Priority.HAZARD) {
            announcement.haptic?.let {
                haptics.fire(it)
                hapticAlreadyFired = true
            }
        }
        commands.trySend(
            Command.Submit(announcement, clock.nowMillis(), hapticAlreadyFired)
        )
    }

    /** Drops queued announcements carrying [tag] and stops one if it is speaking. */
    fun cancelTag(tag: String) {
        commands.trySend(Command.CancelTag(tag))
    }

    /** "Stop." Silences everything including a suspended book. */
    fun stopAll() {
        commands.trySend(Command.StopAll)
    }

    // -- command loop --------------------------------------------------------

    private fun handle(command: Command, scope: CoroutineScope) {
        when (command) {
            is Command.Submit -> onSubmit(command, scope)
            is Command.Finished -> onFinished(command, scope)
            is Command.CancelTag -> onCancelTag(command.tag)
            Command.StopAll -> onStopAll()
        }
    }

    private fun onSubmit(command: Command.Submit, scope: CoroutineScope) {
        val announcement = command.announcement

        // A later announcement with the same tag replaces an earlier one. Five
        // obstacle reports in one second must become one sentence, not five.
        announcement.tag?.let { tag ->
            queue.removeAll { pending ->
                (pending.announcement.tag == tag).also { superseded ->
                    if (superseded) {
                        emit(
                            ArbiterEvent.Dropped(pending.announcement.id, DropReason.SUPERSEDED_BY_SAME_TAG)
                        )
                    }
                }
            }
        }

        // Ambient output is dropped outright, not queued, once the arbiter has
        // been continuously busy. A battery notice two seconds late is noise.
        if (announcement.priority == Priority.AMBIENT && busyForMillis() > Priority.AMBIENT_DROP_AFTER_BUSY_MILLIS) {
            emit(ArbiterEvent.Dropped(announcement.id, DropReason.AMBIENT_WHILE_BUSY))
            return
        }

        queue.add(
            Pending(
                announcement = announcement,
                enqueuedAtMillis = command.submittedAtMillis,
                sequence = ++sequence,
                hapticFired = command.hapticAlreadyFired,
            )
        )
        pump(scope)
    }

    private fun onFinished(command: Command.Finished, scope: CoroutineScope) {
        val active = current ?: return
        if (active.announcement.id != command.announcementId) return
        current = null

        if (command.cancelled) {
            // Preemption already recorded the resume point in [suspendedLongform].
        } else {
            emit(ArbiterEvent.Completed(active.announcement.id))
        }

        if (queue.isEmpty() && current == null) busySinceMillis = null
        pump(scope)
    }

    private fun onCancelTag(tag: String) {
        queue.removeAll { pending ->
            (pending.announcement.tag == tag).also { match ->
                if (match) emit(ArbiterEvent.Dropped(pending.announcement.id, DropReason.CANCELLED))
            }
        }
        // A book suspended behind a hazard carries the tag too. Without this, a
        // reader told to stop hears its page resume the moment the hazard ends.
        if (suspendedLongform?.announcement?.tag == tag) suspendedLongform = null
        current?.takeIf { it.announcement.tag == tag }?.job?.cancel()
    }

    private fun onStopAll() {
        queue.forEach { emit(ArbiterEvent.Dropped(it.announcement.id, DropReason.CANCELLED)) }
        queue.clear()
        suspendedLongform = null
        current?.job?.cancel()
        haptics.silence()
        busySinceMillis = null
    }

    // -- scheduling ----------------------------------------------------------

    private fun pump(scope: CoroutineScope) {
        dropExpired()

        val next = highestPriorityPending()

        if (next == null) {
            // Nothing waiting. If a book was interrupted, pick it back up at the
            // start of the sentence it was cut off in — never mid-word.
            if (current == null) resumeLongformIfAny(scope)
            return
        }

        val active = current
        if (active != null) {
            if (!next.announcement.priority.preempts(active.announcement.priority)) return
            preempt(active, byId = next.announcement.id)
            return // the cancellation callback re-enters pump()
        }

        queue.remove(next)
        start(next, scope)
    }

    private fun preempt(active: Active, byId: Long) {
        val resumeOffset = if (active.announcement.resumable) active.sentenceOffset else null
        if (resumeOffset != null) {
            suspendedLongform = Suspended(active.announcement, resumeOffset)
        }
        emit(ArbiterEvent.Preempted(active.announcement.id, byId, resumeOffset))
        active.job.cancel()
    }

    private fun resumeLongformIfAny(scope: CoroutineScope) {
        val suspended = suspendedLongform ?: return
        suspendedLongform = null

        val remainder = suspended.announcement.text.substring(
            suspended.charOffset.coerceIn(0, suspended.announcement.text.length)
        ).trimStart()
        if (remainder.isEmpty()) return

        emit(ArbiterEvent.Resumed(suspended.announcement.id, suspended.charOffset))
        queue.add(
            Pending(
                announcement = suspended.announcement.copy(text = remainder),
                enqueuedAtMillis = clock.nowMillis(),
                sequence = ++sequence,
                hapticFired = true,
            )
        )
        pump(scope)
    }

    private fun start(pending: Pending, scope: CoroutineScope) {
        val announcement = pending.announcement
        val now = clock.nowMillis()

        if (!pending.hapticFired) announcement.haptic?.let(haptics::fire)
        announcement.earcon?.let(earcons::play)

        if (announcement.text.isBlank()) {
            emit(ArbiterEvent.Completed(announcement.id))
            pump(scope)
            return
        }

        val latency = now - pending.enqueuedAtMillis
        emit(ArbiterEvent.Started(announcement.id, latency))
        if (latency > announcement.priority.budgetMillis) {
            emit(ArbiterEvent.BudgetMissed(announcement.id, announcement.priority.budgetMillis, latency))
        }

        if (busySinceMillis == null) busySinceMillis = now

        val active = Active(announcement = announcement, job = Job())
        current = active

        val job = scope.launch {
            speech.speak(announcement.text, announcement.language) { offset ->
                active.sentenceOffset = offset
            }
        }
        active.job = job
        job.invokeOnCompletion { cause ->
            commands.trySend(Command.Finished(announcement.id, cancelled = cause is CancellationException))
        }
    }

    private fun highestPriorityPending(): Pending? =
        queue.minWithOrNull(
            compareBy<Pending> { it.announcement.priority.rank }.thenBy { it.sequence }
        )

    private fun dropExpired() {
        val now = clock.nowMillis()
        queue.removeAll { pending ->
            val expired = now - pending.enqueuedAtMillis >= pending.announcement.ttlMillis
            if (expired) emit(ArbiterEvent.Dropped(pending.announcement.id, DropReason.EXPIRED))
            expired
        }
    }

    private fun busyForMillis(): Long =
        busySinceMillis?.let { clock.nowMillis() - it } ?: 0L

    private fun emit(event: ArbiterEvent) {
        _events.tryEmit(event)
    }

    // -- internal types ------------------------------------------------------

    private sealed interface Command {
        data class Submit(
            val announcement: Announcement,
            val submittedAtMillis: Long,
            val hapticAlreadyFired: Boolean,
        ) : Command

        data class Finished(val announcementId: Long, val cancelled: Boolean) : Command
        data class CancelTag(val tag: String) : Command
        data object StopAll : Command
    }

    private class Pending(
        val announcement: Announcement,
        val enqueuedAtMillis: Long,
        val sequence: Long,
        val hapticFired: Boolean,
    )

    private class Active(
        val announcement: Announcement,
        var job: Job,
    ) {
        /** Character offset just past the last completed sentence. */
        @Volatile var sentenceOffset: Int = 0
    }

    private class Suspended(
        val announcement: Announcement,
        val charOffset: Int,
    )
}
