"""Effect JSON RPC transport failures use synthetic frames, never a real bearer."""
import json
import unittest
from unittest.mock import patch

from plutonium_agent_toolkit.agent import ws_rpc
from plutonium_agent_toolkit.core.errors import Failure

TOKEN = 'synthetic-secret'


class Socket:
    def __init__(self, frames=(), error=None):
        self.frames = list(frames)
        self.error = error
        self.sent = []
        self.closed = False

    def send(self, data):
        self.sent.append(json.loads(data))

    def recv(self, timeout=None):
        if self.error:
            raise self.error
        frame = self.frames.pop(0)
        if callable(frame):
            frame = frame(self.sent[0]['id'])
        return frame if isinstance(frame, str) else json.dumps(frame)

    def close(self):
        self.closed = True


def success(request_id, value=None):
    return {'_tag': 'Exit', 'requestId': request_id,
            'exit': {'_tag': 'Success', 'value': value or {'sequence': 2}}}


class RpcTests(unittest.TestCase):
    def call(self, sock):
        with patch.object(ws_rpc, 'connect', return_value=sock) as connector:
            result = ws_rpc.call('http://127.0.0.1:3773', TOKEN,
                                 'orchestration.dispatchCommand', {'type': 'run.interrupt'})
        return result, connector

    def test_correlated_batched_exit_and_header_only_auth(self):
        sock = Socket([lambda rid: [success('unrelated'), {'_tag': 'Pong'}, success(rid)]])
        result, connector = self.call(sock)
        self.assertEqual(result, {'sequence': 2})
        args, kwargs = connector.call_args
        self.assertEqual(args, ('ws://127.0.0.1:3773/ws?orchestrationProtocol=2',))
        self.assertEqual(kwargs['additional_headers'], {'Authorization': 'Bearer ' + TOKEN})
        self.assertIsNone(kwargs['proxy'])
        self.assertEqual(kwargs['max_size'], ws_rpc.MAX_BODY)
        self.assertFalse(kwargs['logger'].propagate)
        self.assertNotIn(TOKEN, json.dumps(sock.sent))
        self.assertEqual(sock.sent[0]['_tag'], 'Request')
        self.assertEqual(sock.sent[0]['tag'], 'orchestration.dispatchCommand')
        self.assertEqual(sock.sent[0]['headers'], [])
        self.assertEqual(len(sock.sent), 1)
        self.assertTrue(sock.closed)

    def test_lost_response_is_uncertain_and_never_replayed(self):
        for error in (TimeoutError(TOKEN), OSError(TOKEN)):
            sock = Socket(error=error)
            with self.subTest(error=type(error)), self.assertRaises(Failure) as ctx:
                self.call(sock)
            self.assertEqual(ctx.exception.code, 'delivery_uncertain')
            self.assertNotIn(TOKEN, str(ctx.exception))
            self.assertEqual(len(sock.sent), 1)
            self.assertTrue(sock.closed)

    def test_connect_failure_is_not_a_sent_command(self):
        with patch.object(ws_rpc, 'connect', side_effect=OSError(TOKEN)), self.assertRaises(Failure) as ctx:
            ws_rpc.call('http://127.0.0.1:3773', TOKEN, 'orchestration.launchThread', {})
        self.assertEqual(ctx.exception.code, 'backend_failed')
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_bad_or_oversized_replies_are_uncertain(self):
        for frame in ('not-json', 'x' * (ws_rpc.MAX_BODY + 1), [],
                      lambda rid: {'_tag': 'Exit', 'requestId': rid, 'exit': {}},
                      lambda rid: success(rid, ['wrong-value']),
                      {'_tag': 'Defect', 'defect': TOKEN}):
            sock = Socket([frame])
            with self.subTest(frame=type(frame)), self.assertRaises(Failure) as ctx:
                self.call(sock)
            self.assertEqual(ctx.exception.code, 'delivery_uncertain')
            self.assertNotIn(TOKEN, str(ctx.exception))
            self.assertTrue(sock.closed)

    def test_typed_rejection_is_sanitized(self):
        sock = Socket([lambda rid: {'_tag': 'Exit', 'requestId': rid, 'exit': {
            '_tag': 'Failure', 'cause': [{'_tag': 'Fail', 'error': {
                '_tag': 'OrchestrationV2DispatchCommandError', 'message': TOKEN}}]}}])
        with self.assertRaises(Failure) as ctx:
            self.call(sock)
        self.assertEqual(ctx.exception.code, 'input_invalid')
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_forbidden_scope_is_config_invalid(self):
        sock = Socket([lambda rid: {'_tag': 'Exit', 'requestId': rid, 'exit': {
            '_tag': 'Failure', 'cause': [{'_tag': 'Fail', 'error': {
                '_tag': 'EnvironmentAuthorizationError', 'message': TOKEN}}]}}])
        with self.assertRaises(Failure) as ctx:
            self.call(sock)
        self.assertEqual(ctx.exception.code, 'config_invalid')
        self.assertNotIn(TOKEN, str(ctx.exception))

    def test_no_arbitrary_rpc_method(self):
        with patch.object(ws_rpc, 'connect') as connector, self.assertRaises(Failure):
            ws_rpc.call('http://127.0.0.1:3773', TOKEN, 'terminal.write', {})
        connector.assert_not_called()
