"""Protocol 2 contract fixtures: HTTP projections and one-call Effect RPC writes."""
import copy
import unittest
from unittest.mock import patch

from plutonium_agent_toolkit.agent import t3, t3_v2
from plutonium_agent_toolkit.core.errors import Failure

ORIGIN = 'http://127.0.0.1:3773'
SELECTION = {'instanceId': 'provider-b', 'model': 'chosen-model',
             'options': [{'id': 'reasoningEffort', 'value': 'high'}]}
THREAD = {'id': 'thread-1', 'projectId': 'project-1', 'title': 'Proof',
          'providerInstanceId': 'provider-b', 'modelSelection': SELECTION,
          'runtimeMode': 'approval-required', 'interactionMode': 'plan',
          'worktreePath': None, 'branch': None, 'activeProviderThreadId': 'provider-thread-b'}


def projection(state='running'):
    return {'thread': copy.deepcopy(THREAD),
            'runs': [{'id': 'run-active', 'threadId': 'thread-1', 'ordinal': 1,
                      'status': state, 'providerInstanceId': 'provider-b',
                      'providerThreadId': 'provider-thread-b', 'requestedAt': '2026-09-13T00:00:00Z'}],
            'runtimeRequests': [],
            'providerThreads': [{'id': 'provider-thread-b', 'providerSessionId': 'session-b'}],
            'providerSessions': [{'id': 'session-a', 'providerInstanceId': 'provider-a', 'driver': 'old',
                                  'status': 'error', 'lastError': 'old error', 'updatedAt': '2026-09-13T00:02:00Z'},
                                 {'id': 'session-b', 'providerInstanceId': 'provider-b', 'driver': 'codex',
                                  'status': 'running', 'lastError': None, 'updatedAt': '2026-09-13T00:01:00Z'}],
            'messages': [{'id': 'message-1', 'role': 'user', 'text': 'Proof', 'streaming': False}]}


class V2Tests(unittest.TestCase):
    def setUp(self):
        self.projection = projection()
        self.shell = {'projects': [{'id': 'project-1', 'title': 'Proof', 'workspaceRoot': '/tmp/proof'}],
                      'threads': [{**THREAD, 'status': 'waiting', 'latestRunId': 'run-active',
                                   'activeRunId': 'run-active', 'activityRunStatus': 'waiting',
                                   'pendingRuntimeRequest': {'kind': 'user_input'}}], 'snapshotSequence': 4}
        self.requests = []
        self.http = patch.object(t3, '_request', side_effect=self.request).start()
        self.rpc = patch.object(t3_v2.ws_rpc, 'call', side_effect=self.call).start()
        self.addCleanup(patch.stopall)

    def request(self, origin, method, path, **kwargs):
        self.requests.append((method, path, kwargs))
        if path == t3.DESCRIPTOR_PATH:
            return 200, {'serverVersion': '0.0.40', 'environmentId': 'env-1', 'orchestrationProtocolVersion': 2}
        if path == '/api/orchestration/shell':
            return 200, self.shell
        if path == '/api/orchestration/threads/thread-1':
            return 200, {'projection': self.projection, 'snapshotSequence': 4}
        return 404, {'code': 'not_found'}

    def call(self, origin, bearer, method, payload):
        if method == 'orchestration.launchThread':
            p = projection('starting')
            p['thread']['id'] = payload['threadId']
            return {'threadId': payload['threadId'], 'projection': p, 'resumed': False}
        return {'sequence': 5}

    def dispatch(self, **kwargs):
        return t3.dispatch(ORIGIN, 'synthetic-secret', project_id='project-1', title='Proof',
                           prompt='Reply OK.', selection=SELECTION, **kwargs)

    def test_launch_one_call_with_caller_selection_and_root_workspace(self):
        result = self.dispatch(runtime_mode='approval-required', interaction_mode='plan', branch='proof')
        self.assertEqual(self.rpc.call_count, 1)
        origin, token, method, body = self.rpc.call_args.args
        self.assertEqual(method, 'orchestration.launchThread')
        self.assertEqual(body['workspaceStrategy'], {'type': 'root', 'branch': 'proof'})
        self.assertEqual(body['modelSelection'], SELECTION)
        self.assertEqual(body['initialMessage'], {'messageId': result['message_id'], 'text': 'Reply OK.', 'attachments': []})
        self.assertEqual(body['runtimeMode'], 'approval-required')
        self.assertEqual(body['interactionMode'], 'plan')
        self.assertNotIn('createdAt', body)
        self.assertNotIn('role', body['initialMessage'])
        self.assertEqual(result['thread_id'], body['threadId'])
        self.assertEqual(result['commands'][0]['type'], 'orchestration.launchThread')
        self.assertNotIn('sequence', result['commands'][0], 'launch returns a projection, not a sequence')
        self.assertFalse(result['game_touched'])
        self.assertTrue(all(r[0] == 'GET' for r in self.requests))

    def test_existing_worktree_and_input_validation(self):
        import tempfile
        with tempfile.TemporaryDirectory() as path:
            self.dispatch(worktree_path=path)
            self.assertEqual(self.rpc.call_args.args[3]['workspaceStrategy'],
                             {'type': 'existing_worktree', 'worktreePath': path})
        self.rpc.reset_mock()
        for kwargs in ({'worktree_path': 'relative'}, {'branch': ' '}, {'runtime_mode': 'bogus'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(Failure):
                self.dispatch(**kwargs)
        self.rpc.assert_not_called()

    def test_projection_normalizes_status_and_current_provider_after_switch(self):
        self.projection['runtimeRequests'] = [{'kind': 'command', 'status': 'pending'},
                                              {'kind': 'user_input', 'status': 'pending'}]
        result = t3.status(ORIGIN, 'synthetic-secret', 'thread-1', message_limit=0)
        self.assertEqual(result['turn_state'], 'running')
        self.assertEqual(result['turn_id'], 'run-active')
        self.assertEqual(result['active_run_id'], 'run-active')
        self.assertEqual(result['provider'], 'codex')
        self.assertIsNone(result['session_error'])
        self.assertTrue(result['pending_approvals'])
        self.assertTrue(result['pending_user_input'])
        self.assertEqual(result['recent_messages'], [])
        self.assertEqual(result['message_count'], 1)

    def test_hosts_maps_v2_shell(self):
        result = t3.hosts(ORIGIN, 'synthetic-secret')
        self.assertTrue(result['probe']['drivable'])
        self.assertEqual(result['projects'][0]['id'], 'project-1')
        thread = result['threads'][0]
        self.assertEqual(thread['turn_state'], 'running')
        self.assertEqual(thread['run_state'], 'waiting')
        self.assertTrue(thread['pending_user_input'])

    def test_send_busy_covers_preparing_starting_waiting_and_running(self):
        for state in ('preparing', 'starting', 'waiting', 'running', 'queued'):
            self.projection = projection(state)
            with self.subTest(state=state), self.assertRaises(Failure) as ctx:
                t3.send(ORIGIN, 'synthetic-secret', 'thread-1', 'Next')
            self.assertEqual(ctx.exception.code, 'busy')
        self.rpc.assert_not_called()

    def test_queue_uses_queue_after_active_and_never_overrides_selected_provider(self):
        self.projection['runs'].append({'id': 'run-queued', 'threadId': 'thread-1', 'ordinal': 2, 'status': 'queued'})
        result = t3.send(ORIGIN, 'synthetic-secret', 'thread-1', 'Next', queue=True)
        body = self.rpc.call_args.args[3]
        self.assertEqual(body['type'], 'message.dispatch')
        self.assertEqual(body['dispatchMode'], {'type': 'queue_after_active'})
        self.assertEqual(body['messageId'], result['message_id'])
        self.assertEqual(body['text'], 'Next')
        self.assertEqual(body['createdBy'], 'user')
        self.assertNotIn('modelSelection', body)
        self.assertNotIn('runtimeMode', body)
        self.assertTrue(result['queued_behind_running_turn'])

    def test_idle_followup_starts_immediately(self):
        self.projection = projection('completed')
        result = t3.send(ORIGIN, 'synthetic-secret', 'thread-1', 'Next')
        self.assertEqual(self.rpc.call_args.args[3]['dispatchMode'], {'type': 'start_immediately'})
        self.assertFalse(result['queued_behind_running_turn'])

    def test_interrupt_targets_active_run_not_newer_queued_run(self):
        self.projection['runs'].append({'id': 'run-queued', 'threadId': 'thread-1', 'ordinal': 2, 'status': 'queued'})
        result = t3.interrupt(ORIGIN, 'synthetic-secret', 'thread-1')
        body = self.rpc.call_args.args[3]
        self.assertEqual(body['type'], 'run.interrupt')
        self.assertEqual(body['runId'], 'run-active')
        self.assertEqual(result['run_id'], 'run-active')
        self.assertNotIn('turnId', body)

    def test_interrupt_without_active_run_refuses_without_write(self):
        self.projection = projection('completed')
        with self.assertRaises(Failure) as ctx:
            t3.interrupt(ORIGIN, 'synthetic-secret', 'thread-1')
        self.assertEqual(ctx.exception.code, 'input_invalid')
        self.rpc.assert_not_called()

    def test_missing_or_malformed_projection_does_not_send(self):
        self.projection = {'thread': THREAD}
        with self.assertRaises(Failure) as ctx:
            t3.send(ORIGIN, 'synthetic-secret', 'thread-1', 'Next')
        self.assertEqual(ctx.exception.code, 'input_invalid')
        self.rpc.assert_not_called()
        with self.assertRaises(Failure) as ctx:
            t3.status(ORIGIN, 'synthetic-secret', 'missing')
        self.assertEqual(ctx.exception.code, 'input_missing')

    def test_unconfirmed_launch_preserves_ids_without_retry(self):
        for reply in ({}, {'threadId': 'wrong', 'projection': projection(), 'resumed': False}):
            self.rpc.side_effect = None
            self.rpc.return_value = reply
            self.rpc.reset_mock()
            with self.subTest(reply=reply), self.assertRaises(Failure) as ctx:
                self.dispatch()
            self.assertEqual(ctx.exception.code, 'delivery_uncertain')
            self.assertIn('thread_id', ctx.exception.details)
            self.assertIn('command_id', ctx.exception.details)
            self.assertIn('message_id', ctx.exception.details)
            self.assertEqual(self.rpc.call_count, 1)

    def test_write_loss_and_bad_sequence_carry_ids(self):
        for effect in (Failure('delivery_uncertain', 'lost'), None):
            self.rpc.side_effect = effect
            self.rpc.return_value = {'sequence': True}
            with self.subTest(effect=effect), self.assertRaises(Failure) as ctx:
                t3.send(ORIGIN, 'synthetic-secret', 'thread-1', 'Next', queue=True)
            self.assertEqual(ctx.exception.code, 'delivery_uncertain')
            self.assertEqual(ctx.exception.details['thread_id'], 'thread-1')
            self.assertIn('command_id', ctx.exception.details)
            self.assertIn('message_id', ctx.exception.details)

    def test_failed_and_cancelled_are_not_reported_completed(self):
        for state, expected in [('failed', 'error'), ('cancelled', 'interrupted'), ('rolled_back', 'interrupted')]:
            self.projection = projection(state)
            self.assertEqual(t3.status(ORIGIN, 'synthetic-secret', 'thread-1')['turn_state'], expected)

    def test_cli_dispatch_and_status_keep_the_public_envelope(self):
        from test_agent_routes import invoke
        with patch.object(t3, 'token', return_value='synthetic-secret'):
            code, row = invoke(['agent', 'dispatch', '--origin', ORIGIN, '--project', 'project-1',
                                '--title', 'Proof', '--prompt', 'Reply OK.', '--instance', 'provider-b',
                                '--model', 'chosen-model', '--json'])
            self.assertEqual(code, 0, row)
            self.assertTrue(row['ok'])
            self.assertEqual(row['result']['probe']['orchestration_protocol'], 2)
            code, row = invoke(['agent', 'status', 'thread-1', '--origin', ORIGIN, '--messages', '0', '--json'])
            self.assertEqual(code, 0, row)
            self.assertEqual(row['result']['recent_messages'], [])

    def test_malformed_protocol_is_not_silently_treated_as_v1(self):
        for version in (True, '2', None, 0):
            with patch.object(t3, '_request', return_value=(200, {
                    'serverVersion': 'future', 'environmentId': 'env-1', 'orchestrationProtocolVersion': version})):
                with self.subTest(version=version), self.assertRaises(Failure) as ctx:
                    t3.probe(ORIGIN)
                self.assertEqual(ctx.exception.code, 'input_invalid')

    def test_launch_rejection_keeps_partial_creation_warning(self):
        self.rpc.side_effect = Failure('input_invalid', 'server rejected launch')
        with self.assertRaises(Failure) as ctx:
            self.dispatch()
        self.assertEqual(ctx.exception.code, 'input_invalid')
        self.assertIn('thread creation', ctx.exception.details['note'])
        self.assertIn('thread_id', ctx.exception.details)
        self.assertEqual(self.rpc.call_count, 1)

    def test_opaque_v2_graph_ids_round_trip_through_cli_and_encoded_urls(self):
        from urllib.parse import quote
        from test_agent_routes import invoke
        thread_id = 'thread:delegated-task:command%3A' + 'nested%253Apart%3A' * 15
        self.projection['thread']['id'] = thread_id
        self.projection['runs'][0]['threadId'] = thread_id
        path = '/api/orchestration/threads/' + quote(thread_id, safe='')
        original = self.request

        def request(origin, method, route, **kwargs):
            if route == path:
                return 200, {'projection': self.projection, 'snapshotSequence': 4}
            return original(origin, method, route, **kwargs)

        self.http.side_effect = request
        with patch.object(t3, 'token', return_value='synthetic-secret'):
            code, row = invoke(['agent', 'status', thread_id, '--origin', ORIGIN])
            self.assertEqual(code, 0, row)
            self.assertEqual(row['result']['thread_id'], thread_id)
            self.assertEqual(row['result']['thread_url'], ORIGIN + '/env-1/' + quote(thread_id, safe=''))
            code, row = invoke(['agent', 'send', thread_id, '--origin', ORIGIN, '--prompt', 'Next', '--queue'])
            self.assertEqual(code, 0, row)
            self.assertEqual(self.rpc.call_args.args[3]['threadId'], thread_id)
            code, row = invoke(['agent', 'interrupt', thread_id, '--origin', ORIGIN])
            self.assertEqual(code, 0, row)
            self.assertEqual(self.rpc.call_args.args[3]['threadId'], thread_id)

    def test_cli_dispatch_uses_provider_slug_schema_separately_from_graph_ids(self):
        from test_agent_routes import invoke
        instance = 'P' + 'a' * 63
        with patch.object(t3, 'token', return_value='synthetic-secret'):
            code, row = invoke(['agent', 'dispatch', '--origin', ORIGIN, '--project', 'project-1',
                                '--title', 'Proof', '--prompt', 'Reply OK.', '--instance', instance,
                                '--model', 'chosen-model'])
            self.assertEqual(code, 0, row)
            self.assertEqual(self.rpc.call_args.args[3]['modelSelection']['instanceId'], instance)
            self.rpc.reset_mock()
            for invalid in ('provider/instance:' + 'nested%253Apart%3A' * 20,
                            'a' * 65, '1provider', 'provider.pool'):
                with self.subTest(instance=invalid[:30]):
                    code, row = invoke(['agent', 'dispatch', '--origin', ORIGIN, '--project', 'project-1',
                                        '--title', 'Proof', '--prompt', 'Reply OK.', '--instance', invalid,
                                        '--model', 'chosen-model'])
                    self.assertEqual(code, 1, row)
                    self.assertEqual(row['error_code'], 'input_invalid')
            self.rpc.assert_not_called()

    def test_v2_opaque_id_bounds_preserve_v1_validation(self):
        long_id = 'project:command%3A' + 'part' * 40
        self.assertEqual(t3.validate_id(long_id, 'project id', protocol=2), long_id)
        with self.assertRaises(Failure):
            t3.validate_id(long_id, 'project id', protocol=1)
        for bad in ('', ' leading', 'trailing ', '..', 'a\nheader', 'a' * 4097):
            with self.subTest(bad=bad[:20]), self.assertRaises(Failure):
                t3.validate_id(bad, 'thread id', protocol=2)
