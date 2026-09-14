"""Translate protocol 2 commands and projections into the existing agent route results.

V2 owns provider continuity. Follow-ups don't repeat an old model selection, and interrupts
address an app run, never a provider turn. HTTP reads remain snapshots, not subscriptions.
"""
from __future__ import annotations

import uuid

from ..core.errors import DELIVERY_UNCERTAIN, INPUT_INVALID, Failure
from . import ws_rpc

ACTIVE_STATES = ('preparing', 'starting', 'running', 'waiting')
BUSY_STATES = (*ACTIVE_STATES, 'queued')
RUN_STATES = (*BUSY_STATES, 'completed', 'interrupted', 'failed', 'cancelled', 'rolled_back')
APPROVAL_KINDS = ('command', 'file-read', 'file-change', 'mcp-elicitation')


def _state(state):
    if state in BUSY_STATES:
        return 'running'
    return {'failed': 'error', 'cancelled': 'interrupted', 'rolled_back': 'interrupted',
            'idle': None}.get(state, state)


def shell_thread(thread: dict) -> dict:
    """Preserve raw V2 state beside the compatible turn fields."""
    if thread.get('status') not in (*RUN_STATES, 'idle'):
        raise Failure(INPUT_INVALID, 'The V2 shell has an unknown run status')
    request = thread.get('pendingRuntimeRequest') or {}
    if not isinstance(request, dict) or thread.get('activityRunStatus') not in (*ACTIVE_STATES, None):
        raise Failure(INPUT_INVALID, 'The V2 shell has invalid activity or pending request state')
    raw_state = thread.get('activityRunStatus') or thread['status']
    return {**thread,
            'latestTurn': {'state': _state(raw_state),
                           'turnId': thread.get('activeRunId') or thread.get('latestRunId'),
                           'requestedAt': thread.get('latestRunRequestedAt'),
                           'startedAt': thread.get('activityRunStartedAt') or thread.get('latestRunStartedAt'),
                           'completedAt': None if raw_state in BUSY_STATES else thread.get('latestRunCompletedAt')},
            'session': {'lastError': thread.get('lastError')},
            'hasPendingApprovals': request.get('kind') in APPROVAL_KINDS,
            'hasPendingUserInput': request.get('kind') == 'user_input',
            '_v2': {'run_state': raw_state, 'run_id': thread.get('activeRunId') or thread.get('latestRunId'),
                    'active_run_id': thread.get('activeRunId'), 'latest_run_id': thread.get('latestRunId')}}


def projection_thread(projection: dict, thread_id: str) -> dict:
    """Read only canonical app messages and the session belonging to the selected provider."""
    if not isinstance(projection, dict) or not isinstance(projection.get('thread'), dict):
        raise Failure(INPUT_INVALID, 'The V2 snapshot lacks its thread projection')
    thread = projection['thread']
    arrays = ('runs', 'messages', 'providerSessions', 'providerThreads', 'runtimeRequests')
    if thread.get('id') != thread_id or any(
            not isinstance(projection.get(key), list) or
            any(not isinstance(row, dict) for row in projection[key]) for key in arrays):
        raise Failure(INPUT_INVALID, 'The V2 snapshot has mismatched identity or missing projection arrays')
    runs = projection['runs']
    if any(r.get('status') not in RUN_STATES or type(r.get('ordinal')) is not int or
           r['ordinal'] < 1 or not isinstance(r.get('id'), str) or
           r.get('threadId') != thread_id for r in runs):
        raise Failure(INPUT_INVALID, 'The V2 snapshot has an invalid run')
    runs = sorted(runs, key=lambda r: r['ordinal'])
    latest = runs[-1] if runs else {}
    active = next((r for r in reversed(runs) if r['status'] in ACTIVE_STATES), {})
    current = active or latest
    provider_thread = next((p for p in projection['providerThreads']
                            if p.get('id') == (current.get('providerThreadId') or thread.get('activeProviderThreadId'))), {})
    sessions = [s for s in projection['providerSessions']
                if s.get('providerInstanceId') == (current.get('providerInstanceId') or thread.get('providerInstanceId'))]
    session = next((s for s in sessions if s.get('id') == provider_thread.get('providerSessionId')), None)
    if session is None:
        session = max(sessions, key=lambda s: s.get('updatedAt', ''), default={})
    pending = [r for r in projection['runtimeRequests'] if r.get('status') == 'pending']
    return {**thread, 'messages': projection['messages'],
            'latestTurn': {'state': _state(current.get('status')), 'turnId': current.get('id'),
                           'requestedAt': current.get('requestedAt'), 'startedAt': current.get('startedAt'),
                           'completedAt': current.get('completedAt')},
            'session': {**session, 'providerName': session.get('driver')},
            'hasPendingApprovals': any(r.get('kind') in APPROVAL_KINDS for r in pending),
            'hasPendingUserInput': any(r.get('kind') == 'user_input' for r in pending),
            '_v2': {'run_state': current.get('status'), 'run_id': current.get('id'),
                    'active_run_id': active.get('id'), 'latest_run_id': latest.get('id')}}


def launch(origin: str, bearer: str, info: dict, create: dict, prompt: str) -> dict:
    message_id = str(uuid.uuid4())
    strategy = {'type': 'root'}
    if create['worktreePath'] is not None:
        strategy = {'type': 'existing_worktree', 'worktreePath': create['worktreePath']}
    if create['branch'] is not None:
        strategy['branch'] = create['branch']
    payload = {k: create[k] for k in ('commandId', 'threadId', 'projectId', 'title', 'modelSelection',
                                     'runtimeMode', 'interactionMode')}
    payload.update(workspaceStrategy=strategy,
                   initialMessage={'messageId': message_id, 'text': prompt, 'attachments': []})
    try:
        result = ws_rpc.call(origin, bearer, 'orchestration.launchThread', payload)
        if (result.get('threadId') != create['threadId'] or result.get('resumed') is not False or
                not isinstance(result.get('projection'), dict) or
                not isinstance(result['projection'].get('thread'), dict) or
                result['projection']['thread'].get('id') != create['threadId']):
            raise Failure(DELIVERY_UNCERTAIN, 'The launch reply did not confirm the requested new thread',
                          'Read agent status for the thread_id before repeating anything.')
    except Failure as exc:
        exc.details.update(thread_id=create['threadId'], command_id=create['commandId'], message_id=message_id,
                           note='Inspect this thread_id before another launch; a server error can follow thread creation.')
        raise
    thread_id = create['threadId']
    return {'probe': {k: info[k] for k in ('origin', 'server_version', 'environment_id', 'orchestration_protocol')},
            'thread_id': thread_id, 'message_id': message_id, 'project_id': create['projectId'],
            'title': create['title'], 'model_selection': create['modelSelection'],
            'runtime_mode': create['runtimeMode'], 'interaction_mode': create['interactionMode'],
            'worktree_path': create['worktreePath'], 'branch': create['branch'],
            'commands': [{'command_id': create['commandId'], 'type': 'orchestration.launchThread',
                          'thread_id': thread_id, 'resumed': result['resumed']}],
            'thread_url': f"{origin}/{info['environment_id']}/{thread_id}", 'prompt_chars': len(prompt),
            'game_touched': False,
            'verification': 'The server confirmed launchThread with a thread projection. Read agent status for provider progress; launch is not task completion.'}


def _command(origin: str, bearer: str, command: dict) -> dict:
    try:
        result = ws_rpc.call(origin, bearer, 'orchestration.dispatchCommand', command)
        sequence = result.get('sequence')
        if type(sequence) is not int or sequence < 0:
            raise Failure(DELIVERY_UNCERTAIN, 'The V2 command reply lacks a valid sequence',
                          'Read agent status before repeating anything.')
    except Failure as exc:
        exc.details.update(thread_id=command['threadId'], command_id=command['commandId'])
        for source, target in (('messageId', 'message_id'), ('runId', 'run_id')):
            if source in command:
                exc.details[target] = command[source]
        raise
    return {'command_id': command['commandId'], 'type': command['type'], 'sequence': sequence}


def send(origin: str, bearer: str, current: dict, prompt: str, queue: bool) -> dict:
    message_id = str(uuid.uuid4())
    command = {'type': 'message.dispatch', 'commandId': str(uuid.uuid4()), 'threadId': current['thread_id'],
               'messageId': message_id, 'text': prompt, 'attachments': [],
               'createdBy': 'user', 'creationSource': 'web',
               'dispatchMode': {'type': 'queue_after_active' if queue else 'start_immediately'}}
    accepted = _command(origin, bearer, command)
    return {'thread_id': current['thread_id'], 'message_id': message_id,
            'queued_behind_running_turn': current['turn_state'] == 'running',
            'command': accepted, 'thread_url': current['thread_url'], 'prompt_chars': len(prompt), 'game_touched': False}


def interrupt(origin: str, bearer: str, current: dict) -> dict:
    run_id = current['active_run_id']
    if not run_id:
        raise Failure(INPUT_INVALID, 'The thread has no active V2 run to interrupt; nothing was sent')
    command = {'type': 'run.interrupt', 'commandId': str(uuid.uuid4()),
               'threadId': current['thread_id'], 'runId': run_id}
    accepted = _command(origin, bearer, command)
    return {'thread_id': current['thread_id'], 'turn_id': run_id, 'run_id': run_id,
            'turn_state_before': current['turn_state'], 'command': accepted, 'game_touched': False,
            'verification': 'The interrupt was accepted. Read agent status to see the run stop.'}
