"""
contracts/chat_memory.py

Per-user chat memory, stored in MongoDB (collection: chat_messages).

Rules:
- user_id ALWAYS comes from the JWT (get_current_user), never from the request body.
- Only the human question and the final assistant answer are stored; tool calls /
  observations are not (they're re-fetched fresh from MongoDB every time, so old
  numbers can never go stale inside the history).
- One continuous conversation per user. `clear()` wipes it (the "Clear chat" button).
"""
from datetime import datetime, timezone

COLLECTION = "chat_messages"


class ChatMemory:
    def __init__(self, db):
        self.col = db[COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.col.create_index([("user_id", 1), ("ts", 1)])

    async def append(self, user_id: str, role: str, content: str) -> None:
        if role not in ("user", "assistant"):
            raise ValueError("role must be 'user' or 'assistant'")
        await self.col.insert_one(
            {
                "user_id": user_id,
                "role": role,
                "content": content,
                "ts": datetime.now(timezone.utc),
            }
        )

    async def load(self, user_id: str, limit: int = 10) -> list[dict]:
        """Last `limit` messages for this user, oldest first, as {role, content}."""
        rows = await (
            # _id breaks ties: Mongo timestamps are millisecond-precision, so a question and its
            # answer saved back-to-back can share the same ts.
            self.col.find({"user_id": user_id}).sort([("ts", -1), ("_id", -1)]).limit(limit).to_list(length=limit)
        )
        rows.reverse()
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    async def clear(self, user_id: str) -> int:
        res = await self.col.delete_many({"user_id": user_id})
        return res.deleted_count