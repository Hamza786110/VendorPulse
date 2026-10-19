"""
contracts/chatbot_routes.py

POST   /contracts/chatbot           ask a question (user comes from the JWT)
GET    /contracts/chatbot/history   this user's recent messages (to show on login)
DELETE /contracts/chatbot/history   "Clear chat"

"""
from fastapi import APIRouter, Depends, HTTPException  # type: ignore
from pydantic import BaseModel, Field  # type: ignore

from auth.dependencies import get_current_user, get_db
from contracts import chatbot
from contracts.chatbot_memory import ChatMemory

router = APIRouter(prefix="/contracts/chatbot", tags=["chatbot"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


@router.post("")
async def chat(body: ChatRequest, current_user=Depends(get_current_user), db=Depends(get_db)):
    user_id = str(current_user["_id"])  # from the JWT, never from the request body
    try:
        return await chatbot.answer_question(db, user_id, body.message.strip())
    except Exception as e:
        print(f"[chatbot] failed for user {user_id}: {e!r}")
        raise HTTPException(status_code=503, detail="The assistant is unavailable right now. Please try again.")


@router.get("/history")
async def history(limit: int = 20, current_user=Depends(get_current_user), db=Depends(get_db)):
    msgs = await ChatMemory(db).load(str(current_user["_id"]), max(1, min(limit, 100)))
    return {"messages": msgs}


@router.delete("/history")
async def clear_history(current_user=Depends(get_current_user), db=Depends(get_db)):
    deleted = await ChatMemory(db).clear(str(current_user["_id"]))
    return {"deleted": deleted}