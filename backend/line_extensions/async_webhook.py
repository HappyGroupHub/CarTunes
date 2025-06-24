# -*- coding: utf-8 -*-

#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       https://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

"""This module provides an asynchronous webhook handler for LINE Bot SDK."""

import asyncio
import base64
import hashlib
import hmac
import inspect
import json

from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.models.events import UnknownEvent  ## Special
from linebot.v3.utils import LOGGER, PY3, safe_compare_digest
from linebot.v3.webhooks import (
    Event,
    MessageEvent,
)

if hasattr(hmac, "compare_digest"):
    def compare_digest(val1, val2):
        """compare_digest function.

        If hmac module has compare_digest function, use it.
        Or not, use linebot.v3.utils.safe_compare_digest.

        :param val1: string or bytes for compare
        :type val1: str | bytes
        :param val2: string or bytes for compare
        :type val2: str | bytes
        :rtype: bool
        :return: result
        """
        return hmac.compare_digest(val1, val2)
else:
    def compare_digest(val1, val2):
        """compare_digest function.

        If hmac module has compare_digest function, use it.
        Or not, use linebot.v3.utils.safe_compare_digest.

        :param val1: string or bytes for compare
        :type val1: str | bytes
        :param val2: string or bytes for compare
        :type val2: str | bytes
        :rtype: bool
        :return: result
        """
        return safe_compare_digest(val1, val2)


class SignatureValidator(object):
    """Signature validator.

    https://developers.line.biz/en/reference/messaging-api/#signature-validation
    """

    def __init__(self, channel_secret):
        """__init__ method.

        :param str channel_secret: Channel secret (as text)
        """
        self.channel_secret = channel_secret.encode('utf-8')

    def validate(self, body, signature):
        """Check signature.

        :param str body: Request body (as text)
        :param str signature: X-Line-Signature value (as text)
        :rtype: bool
        """
        gen_signature = hmac.new(
            self.channel_secret,
            body.encode('utf-8'),
            hashlib.sha256
        ).digest()

        return compare_digest(
            signature.encode('utf-8'), base64.b64encode(gen_signature)
        )


class WebhookPayload(object):
    """Webhook Payload.

    https://developers.line.biz/en/reference/messaging-api/#request-body
    """

    def __init__(self, events=None, destination=None):
        """__init__ method.

        :param events: Information about the events.
        :type events: list[T <= :py:class:`linebot.v3.webhooks.models.Event`]
        :param str destination: User ID of a bot that should receive webhook events.
        """
        self.events = events
        self.destination = destination


class AsyncWebhookParser(object):
    """Async Webhook Parser."""

    def __init__(self, channel_secret):
        """__init__ method.

        :param str channel_secret: Channel secret (as text)
        """
        self.signature_validator = SignatureValidator(channel_secret)

    def parse(self, body, signature, as_payload=False):
        """Parse webhook request body as text.

        :param str body: Webhook request body (as text)
        :param str signature: X-Line-Signature value (as text)
        :param bool as_payload: (optional) True to return WebhookPayload object.
        :rtype: list[T <= :py:class:`linebot.v3.webhooks.models.Event`]
            | :py:class:`linebot.v3.async_webhook.WebhookPayload`
        :return: Events list, or WebhookPayload instance
        """
        if not self.signature_validator.validate(body, signature):
            raise InvalidSignatureError(
                'Invalid signature. signature=' + signature)

        body_json = json.loads(body)
        events = []
        for event in body_json['events']:
            try:
                events.append(Event.from_dict(event))
            except ValueError:
                LOGGER.info('Unknown event type. type=' + event['type'])
                events.append(UnknownEvent.new_from_json_dict(event))

        if as_payload:
            return WebhookPayload(events=events, destination=body_json.get('destination'))
        else:
            return events


class AsyncWebhookHandler(object):
    """Async Webhook Handler.

    This handler supports both sync and async handler functions.
    """

    def __init__(self, channel_secret):
        """__init__ method.

        :param str channel_secret: Channel secret (as text)
        """
        self.parser = AsyncWebhookParser(channel_secret)
        self._handlers = {}
        self._default = None

    def add(self, event, message=None):
        """Add handler method.

        :param event: Specify a kind of Event which you want to handle
        :type event: T <= :py:class:`linebot.v3.webhooks.models.Event` class
        :param message: (optional) If event is MessageEvent,
            specify kind of Messages which you want to handle
        :type: message: T <= :py:class:`linebot.v3.webhooks.models.message_content.MessageContent` class
        :rtype: func
        :return: decorator
        """

        def decorator(func):
            if isinstance(message, (list, tuple)):
                for it in message:
                    self.__add_handler(func, event, message=it)
            else:
                self.__add_handler(func, event, message=message)

            return func

        return decorator

    def default(self):
        """Set default handler method.

        :rtype: func
        :return: decorator
        """

        def decorator(func):
            self._default = func
            return func

        return decorator

    async def handle(self, body, signature):
        """Handle webhook asynchronously.

        :param str body: Webhook request body (as text)
        :param str signature: X-Line-Signature value (as text)
        """
        payload = self.parser.parse(body, signature, as_payload=True)

        # Create tasks for all events to handle them concurrently
        tasks = []
        for event in payload.events:
            func = None
            key = None

            if isinstance(event, MessageEvent):
                key = self.__get_handler_key(
                    event.__class__, event.message.__class__)
                func = self._handlers.get(key, None)

            if func is None:
                key = self.__get_handler_key(event.__class__)
                func = self._handlers.get(key, None)

            if func is None:
                func = self._default

            if func is None:
                LOGGER.info('No handler of ' + key + ' and no default handler')
            else:
                # Create a task for each event handler
                task = asyncio.create_task(self.__invoke_func(func, event, payload))
                tasks.append(task)

        # Wait for all tasks to complete
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def __add_handler(self, func, event, message=None):
        key = self.__get_handler_key(event, message=message)
        self._handlers[key] = func

    @classmethod
    async def __invoke_func(cls, func, event, payload):
        """Invoke handler function, supporting both sync and async functions."""
        (has_varargs, args_count) = cls.__get_args_count(func)

        # Prepare arguments based on function signature
        if has_varargs or args_count == 2:
            args = (event, payload.destination)
        elif args_count == 1:
            args = (event,)
        else:
            args = ()

        # Check if the function is async
        if inspect.iscoroutinefunction(func):
            # If it's async, await it
            await func(*args)
        else:
            # If it's sync, run it in a thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, func, *args)

    @staticmethod
    def __get_args_count(func):
        if PY3:
            arg_spec = inspect.getfullargspec(func)
            return (arg_spec.varargs is not None, len(arg_spec.args))
        else:
            arg_spec = inspect.getargspec(func)
            return (arg_spec.varargs is not None, len(arg_spec.args))

    @staticmethod
    def __get_handler_key(event, message=None):
        if message is None:
            return event.__name__
        else:
            return event.__name__ + '_' + message.__name__
