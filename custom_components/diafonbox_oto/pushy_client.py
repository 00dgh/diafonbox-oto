"""Pushy.me Push Notification Client for Multitek DiafonBox."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import aiohttp

_LOGGER = logging.getLogger(__name__)

PUSHY_API_BASE = "https://api.pushy.me"


class PushyClient:
    """Client for Pushy.me push notifications."""

    def __init__(
        self,
        token: str,
        auth: str,
        session: aiohttp.ClientSession,
        callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Initialize Pushy client.
        
        Args:
            token: Device token from getAccount response
            auth: Pushy auth key
            session: aiohttp session
            callback: Callback function for incoming notifications
        """
        self.token = token
        self.auth = auth
        self.session = session
        self.callback = callback
        self._connected = False
        self._topics: list[str] = []
        self._listen_task: asyncio.Task | None = None

    async def authenticate(self) -> bool:
        """Authenticate device with Pushy."""
        try:
            url = f"{PUSHY_API_BASE}/devices/auth"
            data = {
                "auth": self.auth,
                "token": self.token,
            }
            
            async with self.session.post(url, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("success"):
                        _LOGGER.info("Pushy authentication successful")
                        return True
                    
                _LOGGER.error("Pushy authentication failed: %s", await response.text())
                return False
                
        except Exception as err:
            _LOGGER.error("Pushy authentication error: %s", err)
            return False

    async def subscribe(self, topics: list[str]) -> bool:
        """Subscribe to topics.
        
        Args:
            topics: List of topic names to subscribe to
        """
        try:
            url = f"{PUSHY_API_BASE}/devices/subscribe"
            data = {
                "token": self.token,
                "auth": self.auth,
                "topics": topics,
            }
            
            async with self.session.post(url, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("success"):
                        _LOGGER.info("Subscribed to topics: %s", topics)
                        return True
                    
                _LOGGER.error("Topic subscription failed: %s", await response.text())
                return False
                
        except Exception as err:
            _LOGGER.error("Topic subscription error: %s", err)
            return False

    async def unsubscribe(self, topics: list[str]) -> bool:
        """Unsubscribe from topics.
        
        Args:
            topics: List of topic names to unsubscribe from
        """
        try:
            url = f"{PUSHY_API_BASE}/devices/unsubscribe"
            data = {
                "token": self.token,
                "auth": self.auth,
                "topics": topics,
            }
            
            async with self.session.post(url, json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("success"):
                        _LOGGER.info("Unsubscribed from topics: %s", topics)
                        return True
                    
                _LOGGER.error("Topic unsubscription failed: %s", await response.text())
                return False
                
        except Exception as err:
            _LOGGER.error("Topic unsubscription error: %s", err)
            return False

    async def connect(self, topics: list[str]) -> bool:
        """Connect to Pushy and subscribe to topics.
        
        Args:
            topics: List of topics to subscribe to
        """
        # First authenticate
        if not await self.authenticate():
            return False
        
        # Then subscribe to topics
        if not await self.subscribe(topics):
            return False
        
        self._connected = True
        self._topics = topics
        
        # Start long-polling listener
        await self._start_listener()
        
        return True

    async def _start_listener(self):
        """Start long-polling listener for push notifications."""
        _LOGGER.info("Starting Pushy push notification listener...")
        
        async def listen_loop():
            """Long-polling loop for push notifications."""
            while self._connected:
                try:
                    # Pushy.me long-polling endpoint
                    url = f"{PUSHY_API_BASE}/devices/listen"
                    data = {
                        "auth": self.auth,
                        "token": self.token,
                    }
                    
                    # Long-polling request (waits for notification or timeout)
                    async with self.session.post(
                        url,
                        json=data,
                        timeout=aiohttp.ClientTimeout(total=60),  # 60 second timeout
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            
                            # Check if we got a notification
                            if result.get("notification"):
                                notification = result["notification"]
                                _LOGGER.info(
                                    "Received push notification: %s",
                                    notification.get("data", {}),
                                )
                                
                                # Trigger callback
                                if self.callback:
                                    await self.callback(notification)
                        else:
                            _LOGGER.debug(
                                "Pushy listen response: %s",
                                await response.text(),
                            )
                            # Wait a bit before retrying
                            await asyncio.sleep(5)
                            
                except asyncio.TimeoutError:
                    # Timeout is normal for long-polling, just retry
                    _LOGGER.debug("Pushy listen timeout, retrying...")
                    continue
                    
                except Exception as err:
                    _LOGGER.error("Pushy listen error: %s", err)
                    await asyncio.sleep(10)  # Wait before retry
        
        # Start listener in background
        self._listen_task = asyncio.create_task(listen_loop())

    async def disconnect(self) -> None:
        """Disconnect from Pushy."""
        self._connected = False
        
        # Cancel listener task
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        
        # Unsubscribe from all topics
        if self._topics:
            await self.unsubscribe(self._topics)
        
        _LOGGER.info("Pushy client disconnected")

    @property
    def is_connected(self) -> bool:
        """Return if client is connected."""
        return self._connected
