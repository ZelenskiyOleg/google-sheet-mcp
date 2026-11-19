
import os
import secrets
from contextlib import asynccontextmanager

import google.auth
from googleapiclient.discovery import build
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount
import uvicorn


SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
MCP_AUTH_TOKEN = os.environ["MCP_AUTH_TOKEN"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets"
]

mcp = FastMCP(
    "SD Memory",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)

ALLOWED_SHEETS = {
    "Заявки": "A1:L5000",
    "История": "A1:H10000",
    "Сообщения MAX": "A1:H10000",
    "Состояние": "A1:D100",
}


def sheets_service():
    credentials, _ = google.auth.default(scopes=SCOPES)
    return build(
        "sheets",
        "v4",
        credentials=credentials,
        cache_discovery=False,
    )


@mcp.tool()
def memory_health() -> dict:
    """Check access to the Google Sheets memory."""
    service = sheets_service()

    result = service.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID,
        fields="spreadsheetId,properties.title,sheets.properties.title",
    ).execute()

    return {
        "status": "ok",
        "spreadsheet": result["properties"]["title"],
        "sheets": [
            sheet["properties"]["title"]
            for sheet in result.get("sheets", [])
        ],
    }


@mcp.tool()
def memory_read(sheet_name: str) -> dict:
    """Read an approved SD Controller memory sheet."""
    if sheet_name not in ALLOWED_SHEETS:
        raise ValueError("Unknown or forbidden sheet")

    service = sheets_service()

    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{sheet_name}'!{ALLOWED_SHEETS[sheet_name]}",
        valueRenderOption="FORMATTED_VALUE",
    ).execute()

    values = result.get("values", [])

    if not values:
        return {"sheet": sheet_name, "rows": []}

    headers = values[0]

    rows = [
        dict(zip(headers, row))
        for row in values[1:]
    ]

    return {
        "sheet": sheet_name,
        "count": len(rows),
        "rows": rows,
    }


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        token = request.headers.get("authorization", "")
        expected = f"Bearer {MCP_AUTH_TOKEN}"

        if not secrets.compare_digest(token, expected):
            return JSONResponse(
                {"error": "Unauthorized"},
                status_code=401,
            )

        return await call_next(request)


@asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():
        yield


app = Starlette(
    routes=[
        Mount("/mcp", app=mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
)

app.add_middleware(BearerAuthMiddleware)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
    )
