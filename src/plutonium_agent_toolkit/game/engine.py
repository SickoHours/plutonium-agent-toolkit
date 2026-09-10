"""Engine queries over the external console, bracketed by fresh markers.

Only fixed dvar reads, registered-verb checks and reviewed map-setting writes
are permitted through ``query``. Gameplay verbs go through ``Console.send``
one at a time after their guards pass. A reply is accepted only between the
random start and end markers of *this* query, so stale console output can
never be mistaken for a fresh answer.
"""
from __future__ import annotations

import re
import time
import uuid

from ..core.errors import DELIVERY_UNCERTAIN, INPUT_INVALID, Failure

ACK = "pat_ack"
STATE_FIELDS = ("fs_game", "mapname", "sv_running", "sv_cheats")
SETTINGS = ("ui_mapname", "ui_zm_mapstartlocation", "ui_gametype", "g_gametype", "ui_zm_gamemodegroup")
VERBS = frozenset({"map", "map_restart", "fast_restart", "disconnect", "loadmod", "quit"})
MAX_BATCH = 10
_SETTING = re.compile(r'set ([a-z_]+) "([a-z0-9_]+)"')
_HEADER = re.compile(r'^"([^"\r\n]+)" is: "([^"\r\n]*)"')
_LATCHED = re.compile(r'latched: "([^"\r\n]*)".*')


def parse_value(lines, name: str, pending: bool = False):
    """Value of dvar ``name`` from console lines; with ``pending`` prefer its latched value."""
    result = None
    matched = False
    for raw in lines:
        line = re.sub(r"\^[0-9]", "", raw)
        header = _HEADER.match(line)
        if header:
            matched = header[1] == name
            if matched:
                result = header[2]
        elif pending and matched and line.startswith("latched:"):
            value = _LATCHED.fullmatch(line)
            if not value:
                raise Failure(DELIVERY_UNCERTAIN, "Malformed latched dvar value in console output")
            result = value[1]
        elif line.startswith("]"):
            matched = False
    return result


class Engine:
    def __init__(self, console):
        self.console = console

    def query(self, commands, timeout: float = 8) -> list[str]:
        commands = tuple(commands)
        if len(commands) > MAX_BATCH:
            raise Failure(INPUT_INVALID, f"At most {MAX_BATCH} batched checks")
        for command in commands:
            setting = _SETTING.fullmatch(command)
            if command in STATE_FIELDS + SETTINGS or command in {f"cmdlist {verb}" for verb in VERBS}:
                continue
            if setting and setting[1] in SETTINGS:
                continue
            raise Failure(INPUT_INVALID, f"Unsupported engine query: {command!r}")
        start, end = uuid.uuid4().hex, uuid.uuid4().hex
        self.console.send(";".join((f'set {ACK} "{start}"', ACK, *commands, f'set {ACK} "{end}"', ACK)), timeout=timeout)
        deadline = time.monotonic() + timeout
        while True:
            lines = self.console.screen()
            starts = [i for i, line in enumerate(lines) if parse_value([line], ACK) == start]
            if starts:
                ends = [i for i in range(starts[-1] + 1, len(lines)) if parse_value([lines[i]], ACK) == end]
                if ends:
                    return lines[starts[-1] + 1:ends[0]]
            if time.monotonic() >= deadline:
                raise Failure(DELIVERY_UNCERTAIN, "Fresh engine reply timed out; the command will not be repeated")
            time.sleep(0.1)

    def state(self, timeout: float = 8) -> dict:
        fields = STATE_FIELDS + ("g_gametype",)
        lines = self.query(fields, timeout)
        value = {key: parse_value(lines, key) for key in fields}
        if any(item is None for item in value.values()):
            raise Failure(DELIVERY_UNCERTAIN, "Incomplete fresh state; outcome unverified")
        return value

    def registered(self, verb: str) -> None:
        """Refuse to send a verb the running client does not list in cmdlist."""
        if verb not in VERBS:
            raise Failure(INPUT_INVALID, f"Unsupported engine verb {verb!r}")
        lines = self.query((f"cmdlist {verb}",))
        starts = [i for i, line in enumerate(lines) if line == "Command List:"]
        if starts:
            rows = lines[starts[-1] + 1:]
            end = next((i for i, line in enumerate(rows) if re.fullmatch(r"\d+ commands", line)), None)
            if end is not None and verb in rows[:end]:
                return
        raise Failure(DELIVERY_UNCERTAIN, f"The running client did not verify the {verb} command; nothing was sent")
