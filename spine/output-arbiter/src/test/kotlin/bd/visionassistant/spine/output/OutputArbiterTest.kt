package bd.visionassistant.spine.output

import bd.visionassistant.core.Announcement
import bd.visionassistant.core.DropReason
import bd.visionassistant.core.FakeClock
import bd.visionassistant.core.HapticPattern
import bd.visionassistant.core.Language
import bd.visionassistant.core.Priority
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * The arbiter is an actor: submissions go onto a channel and one loop drains
 * it. These tests run on an unconfined dispatcher so that loop executes
 * eagerly, which makes the ordering assertions below say what they appear to
 * say — "after this submission, this is what the user heard" — rather than
 * depending on how many dispatches have been pumped.
 *
 * FakeClock drives TTL and busy-window logic, so nothing here sleeps.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class OutputArbiterTest {

    private val speech = FakeSpeechEngine()
    private val haptics = FakeHapticEngine()
    private val earcons = FakeEarconEngine()
    private val clock = FakeClock()

    @Test
    fun `hazard haptic fires synchronously on submit, before any dispatch`() =
        runTest(UnconfinedTestDispatcher()) {
            val arbiter = arbiter()

            arbiter.submit(
                Announcement.hazard("Obstacle on your left.", Language.ENGLISH, HapticPattern.OBSTACLE_LEFT)
            )

            // The buzz does not wait for a coroutine dispatch. A vibration
            // reaches the user's motor response about 1.3 s before this
            // sentence finishes, and that head start is the whole point.
            assertEquals(listOf(HapticPattern.OBSTACLE_LEFT), haptics.fired)
        }

    @Test
    fun `hazard preempts reading and reading resumes at the sentence boundary`() =
        runTest(UnconfinedTestDispatcher()) {
            val arbiter = arbiter()
            val events = collectEvents(arbiter)

            arbiter.submit(Announcement.reading("First sentence. Second sentence.", Language.ENGLISH))
            assertEquals(listOf("First sentence. Second sentence."), speech.spoken)

            // The engine reports it finished the first sentence.
            speech.reportSentenceBoundary(15)

            arbiter.submit(
                Announcement.hazard("Vehicle approaching.", Language.ENGLISH, HapticPattern.OBSTACLE_AHEAD)
            )

            assertEquals("Vehicle approaching.", speech.spoken.last())
            assertTrue(events.any { it is ArbiterEvent.Preempted && it.resumeCharOffset == 15 })

            speech.finishCurrent()

            assertEquals("Second sentence.", speech.spoken.last())
            assertTrue(events.any { it is ArbiterEvent.Resumed })
        }

    @Test
    fun `ambient is dropped rather than queued once the arbiter has been busy`() =
        runTest(UnconfinedTestDispatcher()) {
            val arbiter = arbiter()
            val events = collectEvents(arbiter)

            arbiter.submit(Announcement.answer("There is a door on your right.", Language.ENGLISH))

            clock.advance(Priority.AMBIENT_DROP_AFTER_BUSY_MILLIS + 1)
            arbiter.submit(Announcement.ambient("Wearable battery seventy two percent.", Language.ENGLISH))

            assertEquals(1, speech.spoken.size)
            assertTrue(events.any { it is ArbiterEvent.Dropped && it.reason == DropReason.AMBIENT_WHILE_BUSY })
        }

    @Test
    fun `a later announcement with the same tag supersedes the queued one`() =
        runTest(UnconfinedTestDispatcher()) {
            val arbiter = arbiter()
            val events = collectEvents(arbiter)

            // A hazard holds the floor, so both maneuvers queue behind it.
            // (Queued behind an *answer* they would not: maneuver outranks
            // answer and would preempt it instead.)
            arbiter.submit(
                Announcement.hazard("Obstacle ahead.", Language.ENGLISH, HapticPattern.OBSTACLE_AHEAD)
            )

            arbiter.submit(Announcement.maneuver("Turn left in fifty metres.", Language.ENGLISH))
            arbiter.submit(Announcement.maneuver("Turn left in twenty metres.", Language.ENGLISH))

            assertTrue(events.any { it is ArbiterEvent.Dropped && it.reason == DropReason.SUPERSEDED_BY_SAME_TAG })

            speech.finishCurrent()

            assertEquals("Turn left in twenty metres.", speech.spoken.last())
        }

    @Test
    fun `an expired maneuver is dropped instead of spoken late`() =
        runTest(UnconfinedTestDispatcher()) {
            val arbiter = arbiter()
            val events = collectEvents(arbiter)

            arbiter.submit(
                Announcement.hazard("Vehicle approaching.", Language.ENGLISH, HapticPattern.OBSTACLE_AHEAD)
            )

            arbiter.submit(Announcement.maneuver("Turn right now.", Language.ENGLISH))
            clock.advance(7_000) // maneuver TTL is 6 s — that corner is behind us
            speech.finishCurrent()

            assertTrue(events.any { it is ArbiterEvent.Dropped && it.reason == DropReason.EXPIRED })
            assertEquals(listOf("Vehicle approaching."), speech.spoken)
        }

    @Test
    fun `an answer is not interrupted by ambient chatter`() =
        runTest(UnconfinedTestDispatcher()) {
            val arbiter = arbiter()

            arbiter.submit(Announcement.answer("There is a person three metres ahead.", Language.ENGLISH))
            arbiter.submit(Announcement.ambient("Connected.", Language.ENGLISH))

            assertEquals(listOf("There is a person three metres ahead."), speech.spoken)
        }

    @Test
    fun `stop all silences motors and discards a suspended book`() =
        runTest(UnconfinedTestDispatcher()) {
            val arbiter = arbiter()

            arbiter.submit(Announcement.reading("A paragraph. Another paragraph.", Language.ENGLISH))
            speech.reportSentenceBoundary(13)

            arbiter.submit(
                Announcement.hazard("Step down ahead.", Language.ENGLISH, HapticPattern.DROP_AHEAD)
            )

            arbiter.stopAll()
            speech.finishCurrent()

            assertEquals(1, haptics.silenced)
            assertTrue(speech.spoken.none { it == "Another paragraph." })
        }

    @Test
    fun `cancelling the reading tag discards a book suspended behind a hazard`() =
        runTest(UnconfinedTestDispatcher()) {
            val arbiter = arbiter()

            arbiter.submit(Announcement.reading("First sentence. Second sentence.", Language.ENGLISH))
            speech.reportSentenceBoundary(15)

            arbiter.submit(
                Announcement.hazard("Step down ahead.", Language.ENGLISH, HapticPattern.DROP_AHEAD)
            )

            arbiter.cancelTag(Announcement.READING_TAG)
            speech.finishCurrent()

            assertEquals(listOf("First sentence. Second sentence.", "Step down ahead."), speech.spoken)
        }

    // -- helpers -------------------------------------------------------------

    private fun TestScope.arbiter() =
        OutputArbiter(speech, haptics, earcons, clock, backgroundScope)

    private fun TestScope.collectEvents(arbiter: OutputArbiter): List<ArbiterEvent> {
        val events = mutableListOf<ArbiterEvent>()
        backgroundScope.launch { arbiter.events.collect { events += it } }
        return events
    }
}
