
import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

from tools import ShopTools
from policy_search import load_docs
from assistant import handle_message


# Load environment variables
load_dotenv()

DB_PATH = os.getenv("DB_PATH", "./data/shopsphere.db")
POLICIES_PATH = os.getenv("POLICIES_PATH", "./data/policies.md")
MANIFEST_PATH = os.getenv("MANIFEST_PATH", "./data/manifest.json")
APP_TODAY = os.getenv("APP_TODAY", "2026-07-01")


# Initialize application tools
tools = ShopTools(DB_PATH, APP_TODAY)
docs = load_docs(POLICIES_PATH, MANIFEST_PATH, APP_TODAY)


# Request model for Swagger UI
class ChatRequest(BaseModel):
    # Optional here so the endpoint can return the assessment-required HTTP 400
    # when either field is missing, rather than silently inserting defaults.
    session_id: str | None = None
    message: str | None = None


# Create FastAPI application
app = FastAPI(
    title="ResolveBot",
    version="0.1.0",
    description="ShopSphere customer support chatbot API"
)

sessions = {}


# Home endpoint
@app.get("/")
def home():
    return {"message": "ResolveBot is running"}


# Chat endpoint
@app.post("/chat")
async def chat(
    body: ChatRequest | None = None,
    x_customer_id: str | None = Header(
        default=None,
        alias="X-Customer-Id"
    )
):
    if body is None:
        raise HTTPException(
            status_code=400,
            detail="Request body is required"
        )

    if (
        not body.session_id
        or not body.session_id.strip()
        or not body.message
        or not body.message.strip()
    ):
        raise HTTPException(
            status_code=400,
            detail="session_id and message are required"
        )


    # Validate customer ID
    if not x_customer_id:
        raise HTTPException(
            status_code=401,
            detail="X-Customer-Id is required"
        )

    with tools.connect() as con:
        customer = con.execute(
            "SELECT customer_id FROM customers WHERE customer_id = ?",
            (x_customer_id,)
        ).fetchone()

    if not customer:
        raise HTTPException(
            status_code=401,
            detail="Unknown customer"
        )

    # Validate session ownership
    sid = body.session_id

    if (
        sid in sessions
        and sessions[sid]["customer_id"] != x_customer_id
    ):
        raise HTTPException(
            status_code=403,
            detail="This session belongs to another customer"
        )

    # Process message using the existing chatbot
    return handle_message(
        body.message,
        x_customer_id,
        tools,
        docs,
        sessions,
        sid
    )
