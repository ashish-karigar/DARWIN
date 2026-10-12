from concurrent.futures import ThreadPoolExecutor
from threading import Event
from app.runtime import AssistantRuntime
from app.runtime_events import RuntimeEvent, current_runtime_request, emit_runtime_event
import asyncio
from uuid import uuid4
from app.services.assistant_api import _run_request
from app.protocol.schemas import AssistantRequest
from datetime import datetime, UTC


def runtime(runner, **options):
    return AssistantRuntime('ack-test', supervisor_runner=runner, activity_publisher=lambda _: True, skill_publisher=lambda *args: True, **options)


def test_calendar_ack_arrives_while_fetch_is_blocked():
    started, release = Event(), Event()
    observed = []
    def fetch(*args):
        started.set()
        assert release.wait(2)
        return 'Two meetings tomorrow.'
    assistant = runtime(fetch)
    assistant.subscribe(observed.append)
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(assistant.submit, 'What is in my calender?')
        assert started.wait(1)
        partials = [event for event in observed if event.final is False]
        assert len(partials) == 1 and partials[0].content == 'Checking your calendar.'
        assert not future.done()
        release.set()
        assert future.result(1).content == 'Two meetings tomorrow.'


def test_new_tool_gets_ack_without_domain_mapping_and_nested_tools_do_not_duplicate():
    observed = []
    def runner(*args):
        request_id, session_id = current_runtime_request()
        for name in ('tool.new_integration', 'tool.another_integration'):
            emit_runtime_event(RuntimeEvent(kind='skill', request_id=request_id, session_id=session_id, skill=name, phase='started'))
        return 'Done.'
    assistant = runtime(runner)
    assistant.subscribe(observed.append)
    assistant.submit('Do that operation')
    assert len([event for event in observed if event.final is False]) == 1


def test_delayed_fallback_arrives_before_unknown_slow_request_finishes():
    acknowledged, release = Event(), Event()
    def runner(*args):
        assert release.wait(2)
        return 'Done.'
    assistant = runtime(runner, acknowledgement_delay=0.03)
    assistant.subscribe(lambda event: acknowledged.set() if event.final is False else None)
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(assistant.submit, 'Do that operation')
        assert acknowledged.wait(1)
        assert not future.done()
        release.set()
        future.result(1)


def test_fast_conversation_and_explicit_opt_out_do_not_ack():
    for options, query in [({}, 'Hello'), ({'enable_acknowledgements': False}, 'Check my calendar')]:
        assistant = runtime(lambda *args: 'Hello.', **options)
        observed = []
        assistant.subscribe(observed.append)
        assistant.submit(query)
        assert not any(event.final is False for event in observed)


def test_cancelled_request_has_no_late_ack():
    started, release, ack = Event(), Event(), Event()
    def runner(*args):
        started.set()
        assert release.wait(2)
        return 'Late result.'
    assistant = runtime(runner, acknowledgement_delay=0.05)
    assistant.subscribe(lambda event: ack.set() if event.final is False else None)
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(assistant.submit, 'Do that operation', 'cancel-ack')
        assert started.wait(1)
        assistant.cancel('cancel-ack')
        assert not ack.wait(0.1)
        release.set()
        try:
            future.result(1)
        except Exception:
            pass
    assert not ack.is_set()


def test_voice_progress_delivery_does_not_block_background_fetch():
    started, release, finished = Event(), Event(), Event()
    def fetch(*args):
        started.set()
        assert release.wait(2)
        finished.set()
        return 'Two meetings tomorrow.'
    request = AssistantRequest.model_validate({'protocolVersion': '1.0', 'messageId': str(uuid4()), 'timestamp': datetime.now(UTC), 'type': 'assistant.request', 'sessionId': 'ack-test', 'content': 'Check my calendar'})
    messages, spoken = [], []
    async def run():
        async def send(message):
            messages.append(message)
        async def speak_progress(content):
            spoken.append(content)
            assert await asyncio.to_thread(started.wait, 1)
            release.set()
            # Fetch must finish while the acknowledgement audio callback is active.
            assert await asyncio.to_thread(finished.wait, 1)
        return await _run_request(send, runtime(fetch), request, on_partial_response=speak_progress)
    result = asyncio.run(run())
    assert result.content == 'Two meetings tomorrow.'
    assert spoken == ['Checking your calendar.']
    responses = [message for message in messages if message['type'] == 'assistant.response']
    assert [message['final'] for message in responses] == [False, True]


def test_statements_do_not_get_domain_acknowledgement():
    from app.services.request_acknowledgement import acknowledgement_for
    assert acknowledgement_for('I like the weather today') is None
