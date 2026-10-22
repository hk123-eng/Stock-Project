"""stock-event-logger: writes every event delivered from the custom EventBridge bus stock-events
to its CloudWatch log group, one JSON line per event. It has no other permissions and returns
a small summary. Event payloads on this bus carry only price data, never keys or URLs."""
import json

MAX_LOG_CHARS = 8000  # keep one log line bounded


def summarize(event):
    return {"source": event.get("source"), "detail_type": event.get("detail-type"),
            "id": event.get("id"), "time": event.get("time")}


def lambda_handler(event, context):
    line = json.dumps({"stock_event": event}, sort_keys=True, default=str)
    print(line[:MAX_LOG_CHARS])
    return {"statusCode": 200, "logged": summarize(event), "truncated": len(line) > MAX_LOG_CHARS}
