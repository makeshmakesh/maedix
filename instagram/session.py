# pylint:disable=all

from realestate.models import (
    ConversationMessage,
)
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

import logging


logger = logging.getLogger(__name__)

from typing import List, Optional
from asgiref.sync import sync_to_async


class MyCustomSession:
    """Custom session backed by the ConversationMessage model."""

    def __init__(self, conversation_id: str, lead):
        self.conversation_id = conversation_id
        self.lead = lead

    async def get_items(self, limit: Optional[int] = None) -> List[dict]:
        """Retrieve messages for this conversation."""
        queryset = ConversationMessage.objects.filter(
            conversation_id=self.conversation_id
        ).order_by("timestamp")
        if limit:
            queryset = queryset[:limit]
        messages = await sync_to_async(list)(queryset)
        res = []
        for m in messages:
            if m.message_text:
                # Map sender_type to OpenAI-compatible roles
                # 'user' -> 'user', 'assistant'/'human_agent' -> 'assistant'
                role = 'user' if m.sender_type == 'user' else 'assistant'
                res.append({"role": role, "content": m.message_text})
        return res

    async def add_items(self, items: List[dict]) -> None:
        """Store new messages."""
        objs = []
        for item in items:
            if not item.get("message_text", ""):
                continue
            objs.append(
                ConversationMessage(
                    lead=self.lead,
                    conversation_id=self.conversation_id,
                    sender_type=item.get("sender_type", "assistant"),
                    message_text=item.get("message_text", ""),
                    message_type=item.get("message_type", "follow_up"),
                    extracted_data=item.get("extracted_data", {}),
                    confidence_score=item.get("confidence_score"),
                    is_from_instagram=item.get("is_from_instagram", False),
                    instagram_message_id=item.get("instagram_message_id", None),
                )
            )
        await sync_to_async(ConversationMessage.objects.bulk_create)(objs)

    async def pop_item(self) -> Optional[dict]:
        """Remove and return the latest message."""
        latest = await sync_to_async(
            lambda: ConversationMessage.objects.filter(
                conversation_id=self.conversation_id
            )
            .order_by("-timestamp")
            .first()
        )()
        if not latest:
            return None
        data = {
            "sender_type": latest.sender_type,
            "message_text": latest.message_text,
            "timestamp": latest.timestamp.isoformat(),
            "message_type": latest.message_type,
        }
        await sync_to_async(latest.delete)()
        return data

    async def clear_session(self) -> None:
        """Delete all messages for this conversation."""
        await sync_to_async(
            lambda: ConversationMessage.objects.filter(
                conversation_id=self.conversation_id
            ).delete()
        )()
