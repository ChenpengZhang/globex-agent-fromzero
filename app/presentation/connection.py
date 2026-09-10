from fastapi import WebSocket, WebSocketDisconnect

from app.infrastructure.eventbus import (
    InMemoryTradeEventBus,
)


class ConnectionManager:
    def __init__(
        self,
        event_bus: InMemoryTradeEventBus,
    ) -> None:
        self._event_bus = event_bus

    async def serve(
        self,
        websocket: WebSocket,
    ) -> None:
        await websocket.accept()
        # accept the upgrade from HTTP to WebSocket from frontend.

        try:
            subscription = await websocket.receive_json()
            # wait for frontend to send subscription and id.
        except WebSocketDisconnect:
            return

        if not isinstance(subscription, dict):
            await websocket.close(
                code=4000,
                reason="订阅消息必须是 JSON 对象",
            )
            return

        shopping_session_id = str(
            subscription.get(
                "shopping_session_id",
                "",
            )
        ).strip()

        if not shopping_session_id:
            await websocket.close(
                code=4000,
                reason="缺少 shopping_session_id",
            )
            return

        queue = self._event_bus.subscribe(
            shopping_session_id,
        )

        try:
            while True:
                event = await queue.get()
                # wait for backend eventbus to create event
                await websocket.send_json(
                    event.to_dict()
                )
                # send the event to the frontend (browser)

        except WebSocketDisconnect:
            pass

        finally:
            self._event_bus.unsubscribe(
                shopping_session_id,
                queue,
            )
