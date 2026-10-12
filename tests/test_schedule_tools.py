import json
from datetime import datetime, timedelta
from unittest.mock import patch

from app.safety.models import ExecutionResult, ActionOutcome
from app.tools.schedule import create_calendar_event, create_reminder, list_schedule, resolve_day, local_zone
from app.tools.capabilities import capability_snapshot
from app.agents.supervisor import run_supervisor, _PRODUCTIVITY_FOLLOWUP
from app.runtime_events import runtime_event_context
from app.agents.productivity_agent import summarize_schedule


def test_missing_dates_do_not_write():
    with patch('app.tools.schedule.invoke_native') as native:
        value = json.loads(create_calendar_event.invoke({'title': 'Dentist'}))
        assert value['question']
        value = json.loads(create_reminder.invoke({'title': 'Call mom'}))
        assert value['question']
        native.assert_not_called()


def test_invalid_intervals_and_naive_times_do_not_write():
    with patch('app.tools.schedule.invoke_native') as native:
        for start, end in [('2026-09-18T10:00:00', '2026-09-18T11:00:00'), ('2026-09-18T11:00:00-04:00', '2026-09-18T10:00:00-04:00')]:
            result = json.loads(create_calendar_event.invoke({'title': 'Dentist', 'start_at': start, 'end_at': end}))
            assert result['ok'] is False
        native.assert_not_called()


def test_tomorrow_is_local_calendar_day():
    assert resolve_day('tomorrow') == datetime.now(local_zone()).date() + timedelta(days=1)


def test_schedule_returns_real_native_result():
    with patch('app.tools.schedule.execute_guarded') as guard:
        guard.return_value = ExecutionResult(outcome=ActionOutcome.SUCCEEDED, value={'ok': False, 'error': 'access_denied'})
        assert json.loads(list_schedule.invoke({'day': 'tomorrow'}))['error'] == 'access_denied'
        assert guard.call_args.args[0] == 'calendar.list'


def test_registry_contains_actual_tools_and_apps():
    snapshot = capability_snapshot()
    names = {item['name'] for item in snapshot['tools']}
    assert {'list_schedule', 'create_calendar_event', 'delete_calendar_event', 'create_reminder', 'list_reminders', 'control_app', 'control_camera'} <= names
    assert any(app['name'] == 'YouTube' for app in snapshot['apps'])


def test_new_registered_tools_appear_without_prompt_changes():
    from app.agents.productivity_agent import PRODUCTIVITY_TOOLS
    from langchain_core.tools import tool
    @tool
    def inspect_focus_sessions() -> str:
        """Inspect focus sessions."""
        return '{}'
    PRODUCTIVITY_TOOLS.append(inspect_focus_sessions)
    try:
        assert any(item['name'] == 'inspect_focus_sessions' for item in capability_snapshot()['tools'])
    finally:
        PRODUCTIVITY_TOOLS.remove(inspect_focus_sessions)


def test_capability_question_bypasses_model():
    with patch('app.agents.supervisor.supervisor') as model:
        response = run_supervisor('What tools do you have at your disposal?', 'capability-test')
        assert 'calendar and reminders' in response and 'YouTube' in response
        model.invoke.assert_not_called()


def test_schedule_clarification_carries_followup_to_specialist():
    with patch('app.agents.supervisor.ask_productivity_specialist') as agent:
        agent.invoke.side_effect = ['What day should I schedule it?', 'What time should I use?', 'Added it.']
        assert run_supervisor('Add dentist to my schedule', 'schedule-test').endswith('?')
        assert run_supervisor('Tomorrow', 'schedule-test').endswith('?')
        assert run_supervisor('10 am for an hour', 'schedule-test') == 'Added it.'
        assert agent.invoke.call_count == 3
    _PRODUCTIVITY_FOLLOWUP.discard('schedule-test')


def test_busy_schedule_is_grouped_not_read_in_full():
    events = [{'title': f'Event {index}', 'startDate': f'2026-09-18T{index+9:02d}:00:00-04:00', 'allDay': False} for index in range(6)]
    response = summarize_schedule({'ok': True, 'events': events}, 'tomorrow')
    assert '6 commitments' in response
    assert 'Event 0' in response and 'Event 5' not in response
    assert summarize_schedule({'ok': False, 'error': 'access_denied'}, 'tomorrow') != 'Your calendar is clear tomorrow.'


def test_summary_prioritizes_meetings_conflicts_and_health_not_routine():
    def event(title, start, end, **fields):
        return {'title': title, 'startDate': f'2026-09-21T{start}:00-04:00', 'endDate': f'2026-09-21T{end}:00-04:00', 'allDay': False, **fields}
    events = [
        event('Yom Kippur', '00:00', '23:59', allDay=True, calendar='US Holidays'),
        event('Wake up and Get Ready', '07:00', '08:00'),
        event('Study Block 1 (DSA + Python)', '08:00', '10:00'),
        event('i9 Meeting', '10:00', '10:30'),
        event('Job Applications', '10:00', '12:00'),
        event('Internship Meeting', '12:00', '12:30'),
        event('Lunch', '12:30', '13:00'),
        event('Internship Work', '13:00', '14:00'),
        event('Penn Health', '14:00', '17:00'),
        event('Coffee + Networking', '17:00', '18:00'),
        event('Study Block 2', '18:00', '20:00'),
        event('Dinner + Relaxation', '20:00', '23:00'),
    ]
    summary = summarize_schedule({'ok': True, 'events': events}, '2026-09-21')
    assert 'two meetings' in summary
    assert 'i9 Meeting overlaps with Job Applications at 10 am' in summary
    assert 'Penn Health' in summary
    assert 'EDT' not in summary and 'EST' not in summary
    assert 'Yom Kippur' not in summary and 'Dinner' not in summary and 'Study Block' not in summary
    assert 'as usual' not in summary
    assert len(summary.split()) < 65


def test_natural_date_model_route_uses_actual_read_for_summary():
    from app.agents.productivity_agent import run_productivity_agent
    from langchain_core.messages import AIMessage
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    def model_read(*args, **kwargs):
        # ToolNode may execute tools in copied worker contexts.
        context = copy_context()
        with ThreadPoolExecutor(max_workers=1) as worker:
            worker.submit(context.run, list_schedule.invoke, {'day': '2026-09-21'}).result()
        return {'messages': [AIMessage(content='A long itinerary with every event and EDT.') ]}
    payload = {'ok': True, 'events': [{'title': 'Dentist appointment', 'startDate': '2026-09-21T14:00:00-04:00', 'endDate': '2026-09-21T15:00:00-04:00', 'allDay': False}]}
    with runtime_event_context(lambda event: None, 'test-request', 'natural-date-test'), patch('app.tools.schedule.execute_guarded', return_value=ExecutionResult(outcome=ActionOutcome.SUCCEEDED, value=payload)), patch('app.agents.productivity_agent.productivity_agent') as agent:
        agent.invoke.side_effect = model_read
        response = run_productivity_agent('Give me a summary of September 21')
    assert 'Dentist appointment' in response
    assert 'long itinerary' not in response and 'EDT' not in response


def test_adjacent_events_and_all_day_holidays_are_not_conflicts():
    events = [
        {'title': 'Holiday', 'allDay': True, 'calendar': 'Holidays', 'startDate': '2026-09-21T00:00:00-04:00', 'endDate': '2026-09-22T00:00:00-04:00'},
        {'title': 'First meeting', 'allDay': False, 'startDate': '2026-09-21T10:00:00-04:00', 'endDate': '2026-09-21T11:00:00-04:00'},
        {'title': 'Second meeting', 'allDay': False, 'startDate': '2026-09-21T11:00:00-04:00', 'endDate': '2026-09-21T12:00:00-04:00'},
    ]
    assert 'overlap' not in summarize_schedule({'ok': True, 'events': events}, 'tomorrow')


def test_delete_denial_never_reaches_native_helper():
    from app.tools.schedule import delete_calendar_event
    with patch('app.safety.executor.request_confirmation', return_value=False), patch('app.tools.schedule.invoke_native') as native:
        response = json.loads(delete_calendar_event.invoke({'event_id': 'exact-event-id', 'title': 'Dentist'}))
        assert response['ok'] is False
        native.assert_not_called()


def test_cancellation_exits_scheduling_followup():
    _PRODUCTIVITY_FOLLOWUP.add('cancel-test')
    assert run_supervisor('Never mind', 'cancel-test') == 'Cancelled.'
    assert 'cancel-test' not in _PRODUCTIVITY_FOLLOWUP


def test_desktop_app_command_is_emitted():
    from app.tools.apps import control_app
    observed = []
    with runtime_event_context(observed.append, 'request-1', 'desktop'):
        result = json.loads(control_app.invoke({'app_name': 'YouTube', 'action': 'open'}))
    assert result['ok'] is True
    assert observed[0].command == 'app.command'
    assert observed[0].payload == {'appId': 'darwin.youtube', 'action': 'open'}
