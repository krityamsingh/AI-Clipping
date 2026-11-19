"""Read-only Twitch IRC collection with bounded memory and arrival-time counters."""
import re
import secrets
import socket
import ssl
import threading
import time
from collections import deque

from src.stream_highlights import _CHAT_HYPE


def channel_name(value):
    value = str(value or "").strip().lower()
    if value.startswith(("https://www.twitch.tv/", "https://twitch.tv/")):
        value = value.rstrip("/").rsplit("/", 1)[-1]
    value = value.lstrip("#")
    if value and not re.fullmatch(r"[a-z0-9_]{1,25}", value):
        raise ValueError("Twitch channel must be a channel name or https://twitch.tv/name")
    return value


class TwitchChat:
    def __init__(self, channel, stop_event, *, capacity=100000):
        self.channel = channel_name(channel)
        self.stop_event = stop_event
        self.events = deque(maxlen=capacity)
        self.lock = threading.Lock()
        self.connected = False
        self.error = None
        self.total = 0
        self.dropped = 0
        self.thread = None

    def ingest(self, line, now=None):
        """Accept PRIVMSG only; do not retain usernames or raw message text."""
        match = re.search(r"(?:^| )PRIVMSG #([a-zA-Z0-9_]+) :(.*)$", line)
        if not match or match[1].lower() != self.channel:
            return False
        with self.lock:
            if len(self.events) == self.events.maxlen:
                self.dropped += 1
            self.events.append((time.monotonic() if now is None else now,
                                bool(_CHAT_HYPE.search(match[2]))))
            self.total += 1
        return True

    def relative_events(self, origin, start, end, offset=0):
        # Arrival times are approximate: playback latency is not inferable from IRC.
        with self.lock:
            return [{"timestamp": round(t - origin + offset - start, 3), "hype": hype}
                    for t, hype in self.events if start <= t - origin + offset < end]

    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            recent = sum(t >= now - 5 for t, _ in self.events)
            baseline = sum(now - 65 <= t < now - 5 for t, _ in self.events) / 12
            return {"channel": self.channel, "connected": self.connected,
                    "error": self.error, "messages_total": self.total,
                    "messages_last_5s": recent,
                    "baseline_messages_per_5s": round(baseline, 2),
                    "spike_ratio": round(recent / max(1, baseline), 2),
                    "buffer_evictions": self.dropped,
                    "alignment": "estimated_from_arrival_time"}

    def start(self):
        if self.channel:
            self.thread = threading.Thread(target=self._run, name="twitch-chat", daemon=True)
            self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                with socket.create_connection(("irc.chat.twitch.tv", 6697), timeout=5) as raw:
                    with ssl.create_default_context().wrap_socket(
                            raw, server_hostname="irc.chat.twitch.tv") as connection:
                        connection.settimeout(1)
                        nick = "justinfan" + str(secrets.randbelow(90000000) + 10000000)
                        connection.sendall((f"NICK {nick}\r\nJOIN #{self.channel}\r\n").encode())
                        buffer = b""
                        last_data = time.monotonic()
                        while not self.stop_event.is_set():
                            try:
                                data = connection.recv(16384)
                            except socket.timeout:
                                if time.monotonic() - last_data > 300:
                                    raise ConnectionError("Chat connection timed out")
                                continue
                            if not data:
                                raise ConnectionError("Chat disconnected")
                            last_data = time.monotonic()
                            buffer += data
                            if len(buffer) > 1024 * 1024:
                                raise ConnectionError("Oversized IRC message")
                            while b"\r\n" in buffer:
                                row, buffer = buffer.split(b"\r\n", 1)
                                line = row.decode("utf-8", errors="replace")
                                if line.startswith("PING "):
                                    connection.sendall(("PONG " + line[5:] + "\r\n").encode())
                                elif " RECONNECT" in line:
                                    raise ConnectionError("Twitch requested reconnect")
                                elif f" JOIN #{self.channel}" in line or " 366 " in line:
                                    self.connected, self.error = True, None
                                elif "Login authentication failed" in line or "Improperly formatted auth" in line:
                                    raise ConnectionError("Twitch rejected anonymous chat access")
                                self.ingest(line)
            except (OSError, ValueError) as exc:
                self.error = str(exc)
            finally:
                self.connected = False
            self.stop_event.wait(5)
