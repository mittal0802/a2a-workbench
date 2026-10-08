"""A delegating grpc.aio server-streaming call with hooks on every read."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import grpc

MessageHook = Callable[[Any], Awaitable[Any]]
EndHook = Callable[[BaseException | None], Awaitable[None]]
BeforeReadHook = Callable[[], Awaitable[None]]
ReadTimeout = Callable[[], float | None]
TimeoutError_ = Callable[[], BaseException]


class UnaryStreamCallProxy(grpc.aio.UnaryStreamCall):
    """Wraps a server-streaming call, passing each message through hooks.

    ``before_read`` may raise to fail the next read, ``read_timeout`` bounds
    how long one read may block (raising ``on_timeout()`` when exceeded),
    ``on_message`` sees (and returns) every message, and ``on_end`` runs once
    with the terminating exception or ``None`` at end of stream. Both
    ``read()`` and ``async for`` go through the hooks; every other method
    delegates to the wrapped call.
    """

    def __init__(
        self,
        call: Any,
        *,
        before_read: BeforeReadHook | None = None,
        on_message: MessageHook | None = None,
        on_end: EndHook | None = None,
        read_timeout: ReadTimeout | None = None,
        on_timeout: TimeoutError_ | None = None,
    ) -> None:
        self._call = call
        self._read_timeout = read_timeout
        self._on_timeout = on_timeout
        self._before_read = before_read
        self._on_message = on_message
        self._on_end = on_end
        self._ended = False

    async def _end(self, error: BaseException | None) -> None:
        if self._ended:
            return
        self._ended = True
        if self._on_end is not None:
            await self._on_end(error)

    async def read(self) -> Any:
        """Read the next message (or ``grpc.aio.EOF``) through the hooks."""
        try:
            if self._before_read is not None:
                await self._before_read()
            timeout = self._read_timeout() if self._read_timeout else None
            if timeout is None:
                message = await self._call.read()
            else:
                try:
                    message = await asyncio.wait_for(self._call.read(), max(timeout, 0))
                except TimeoutError:
                    self._call.cancel()
                    raise (self._on_timeout() if self._on_timeout else TimeoutError()) from None
            if message is grpc.aio.EOF:
                await self._end(None)
                return message
            if self._on_message is not None:
                message = await self._on_message(message)
            return message
        except BaseException as exc:
            await self._end(exc)
            raise

    async def _iterate(self) -> AsyncIterator[Any]:
        while True:
            message = await self.read()
            if message is grpc.aio.EOF:
                return
            yield message

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._iterate()

    def cancelled(self) -> bool:
        return bool(self._call.cancelled())

    def done(self) -> bool:
        return bool(self._call.done())

    def time_remaining(self) -> float | None:
        return self._call.time_remaining()  # type: ignore[no-any-return]

    def cancel(self) -> bool:
        return bool(self._call.cancel())

    def add_done_callback(self, callback: Any) -> None:
        self._call.add_done_callback(callback)

    async def initial_metadata(self) -> Any:
        return await self._call.initial_metadata()

    async def trailing_metadata(self) -> Any:
        return await self._call.trailing_metadata()

    async def code(self) -> grpc.StatusCode:
        return await self._call.code()  # type: ignore[no-any-return]

    async def details(self) -> str:
        return await self._call.details()  # type: ignore[no-any-return]

    async def wait_for_connection(self) -> None:
        await self._call.wait_for_connection()


class _UnaryUnaryAdapter(grpc.aio.UnaryUnaryClientInterceptor):
    def __init__(self, target: Any) -> None:
        self._target = target

    async def intercept_unary_unary(self, continuation: Any, details: Any, request: Any) -> Any:
        return await self._target.intercept_unary_unary(continuation, details, request)


class _UnaryStreamAdapter(grpc.aio.UnaryStreamClientInterceptor):
    def __init__(self, target: Any) -> None:
        self._target = target

    async def intercept_unary_stream(self, continuation: Any, details: Any, request: Any) -> Any:
        return await self._target.intercept_unary_stream(continuation, details, request)


def as_channel_interceptors(target: Any) -> list[Any]:
    """Return one grpc.aio interceptor per call type, all delegating to ``target``.

    grpc.aio registers an interceptor object under a single call type, so an
    object handling both unary and server-streaming calls needs one adapter each.
    """
    return [_UnaryUnaryAdapter(target), _UnaryStreamAdapter(target)]
