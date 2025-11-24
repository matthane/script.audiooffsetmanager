"""Lightweight event bus to manage subscriptions and optional runtime logging."""

import time
import xbmc
from resources.lib.logger import log


class EventBus:
    def __init__(self, log_runtimes=False):
        self._subscribers = {}
        self.log_runtimes = log_runtimes

    def subscribe(self, event_name, callback):
        if event_name not in self._subscribers:
            self._subscribers[event_name] = []
        self._subscribers[event_name].append(callback)

    def unsubscribe(self, event_name, callback):
        if event_name in self._subscribers:
            self._subscribers[event_name] = [
                cb for cb in self._subscribers[event_name] if cb != callback
            ]
            if not self._subscribers[event_name]:
                del self._subscribers[event_name]

    def publish(self, event_name, *args, **kwargs):
        callbacks = self._subscribers.get(event_name, [])
        for callback in callbacks:
            start = time.time()
            callback(*args, **kwargs)
            if self.log_runtimes:
                elapsed = (time.time() - start) * 1000
                callback_name = self._format_callback_name(callback)
                log(f"AOM_EventBus: {event_name} handled by {callback_name} in {elapsed:.1f}ms",
                    xbmc.LOGDEBUG)

    def _format_callback_name(self, callback):
        """Return a readable name for logging, including owner class when available."""
        try:
            if hasattr(callback, "__self__") and callback.__self__ is not None:
                owner = callback.__self__.__class__.__name__
                func = getattr(callback, "__name__", str(callback))
                return f"{owner}.{func}"
            return getattr(callback, "__name__", str(callback))
        except Exception:
            return str(callback)
