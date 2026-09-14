"""Exercise the actual WebSocket dependency against synthetic loopback peers."""
import json
import logging
import threading
import unittest
from contextlib import contextmanager
from http import HTTPStatus

from websockets.datastructures import Headers
from websockets.http11 import Response
from websockets.sync.server import serve

from plutonium_agent_toolkit.agent import ws_rpc
from plutonium_agent_toolkit.core.errors import Failure

SECRET = 'synthetic-upgrade-secret'
QUIET = logging.Logger('pat-test-ws-peer')
QUIET.disabled = True
QUIET.propagate = False


@contextmanager
def peer(handler, process_request=None):
    with serve(handler, '127.0.0.1', 0, process_request=process_request,
               logger=QUIET, close_timeout=0.1) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.socket.getsockname()[1]}'
        finally:
            server.shutdown()
            thread.join(timeout=2)


class WebSocketPeerTests(unittest.TestCase):
    def test_actual_upgrade_and_effect_exchange(self):
        requests = []

        def handler(sock):
            request = json.loads(sock.recv(timeout=1))
            requests.append((sock.request.path, sock.request.headers.get('Authorization'), request))
            sock.send(json.dumps([{'_tag': 'Pong'}, {'_tag': 'Exit', 'requestId': request['id'],
                            'exit': {'_tag': 'Success', 'value': {'sequence': 9}}}]))

        with peer(handler) as origin:
            result = ws_rpc.call(origin, SECRET, 'orchestration.dispatchCommand',
                                 {'type': 'run.interrupt', 'commandId': 'command-1',
                                  'threadId': 'thread-1', 'runId': 'run-1'})
        self.assertEqual(result, {'sequence': 9})
        self.assertEqual(len(requests), 1)
        path, authorization, request = requests[0]
        self.assertEqual(path, '/ws?orchestrationProtocol=2')
        self.assertEqual(authorization, 'Bearer ' + SECRET)
        self.assertEqual(request['_tag'], 'Request')
        self.assertEqual(request['headers'], [])
        self.assertNotIn(SECRET, json.dumps(request))

    def test_upgrade_rejections_and_redirect_are_never_followed(self):
        received = []

        def handler(sock):
            received.append(sock.request.path)

        with peer(handler) as target:
            for status, code in ((401, 'config_invalid'), (403, 'config_invalid'),
                                 (426, 'not_implemented'), (302, 'backend_failed')):
                def reject(connection, request):
                    headers = Headers([('Location', target.replace('http:', 'ws:') + '/redirected')])
                    return Response(status, HTTPStatus(status).phrase, headers, SECRET.encode())

                with self.subTest(status=status), peer(handler, reject) as origin:
                    with self.assertRaises(Failure) as ctx:
                        ws_rpc.call(origin, SECRET, 'orchestration.launchThread', {}, timeout=1)
                    self.assertEqual(ctx.exception.code, code)
                    self.assertNotIn(SECRET, json.dumps(ctx.exception.to_dict()))
        self.assertEqual(received, [], 'no upgrade accepted and no redirect target contacted')

    def test_closed_connection_after_write_is_uncertain(self):
        received = []

        def handler(sock):
            received.append(sock.recv(timeout=1))
            sock.close(reason=SECRET)

        with peer(handler) as origin, self.assertRaises(Failure) as ctx:
            ws_rpc.call(origin, SECRET, 'orchestration.launchThread', {}, timeout=1)
        self.assertEqual(ctx.exception.code, 'delivery_uncertain')
        self.assertEqual(len(received), 1)
        self.assertNotIn(SECRET, json.dumps(ctx.exception.to_dict()))

    def test_no_reply_deadline_is_uncertain(self):
        received = []
        release = threading.Event()

        def handler(sock):
            received.append(sock.recv(timeout=1))
            release.wait(timeout=3)

        with peer(handler) as origin:
            try:
                with self.assertRaises(Failure) as ctx:
                    ws_rpc.call(origin, SECRET, 'orchestration.launchThread', {}, timeout=0.5)
                self.assertEqual(ctx.exception.code, 'delivery_uncertain')
            finally:
                release.set()
        self.assertEqual(len(received), 1)
