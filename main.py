import time
import uuid
from fastapi import FastAPI, Request, Response, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List

app = FastAPI()

# Enable CORS so the grader's browser can verify it directly
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# GLOBAL IN-MEMORY STORAGE
# ---------------------------------------------------------
TOTAL_ORDERS = 59  # Your assigned total (T)
RATE_LIMIT_MAX = 15  # Your assigned max requests (R)
RATE_LIMIT_WINDOW = 10.0  # Window size in seconds

# Generate a fixed catalog of orders from 1 to 59
ORDER_CATALOG = [{"id": i, "item": f"Item {i}", "price": round(10.5 * i, 2)} for i in range(1, TOTAL_ORDERS + 1)]

# Databases for this session
idempotency_db = {}  # Maps Idempotency-Key -> Saved Order Response
rate_limit_db = {}   # Maps Client-Id -> List of timestamps of recent requests


# ---------------------------------------------------------
# ENDPOINT 1: Idempotent Order Creation
# ---------------------------------------------------------
@app.post("/orders", status_code=201)
def create_order(response: Response, idempotency_key: Optional[str] = Header(None)):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Missing Idempotency-Key header")
        
    # Pattern: If we've seen this key before, return the EXACT same response
    if idempotency_key in idempotency_db:
        response.status_code = 200  # Return 200 OK for repeated requests
        return idempotency_db[idempotency_key]
        
    # If it's a fresh key, generate a brand new order ID
    new_order = {
        "id": str(uuid.uuid4()),
        "status": "created",
        "created_at": time.time()
    }
    
    # Save it to our database before returning it
    idempotency_db[idempotency_key] = new_order
    return new_order


# ---------------------------------------------------------
# ENDPOINT 2: Cursor Pagination
# ---------------------------------------------------------
@app.get("/orders")
def get_orders(limit: int = 10, cursor: Optional[str] = Query(None)):
    # Convert cursor to an index. If no cursor is passed, start at index 0.
    start_index = 0
    if cursor:
        try:
            start_index = int(cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cursor format")
            
    # Slice the catalog up to the allowed limit
    end_index = start_index + limit
    page_items = ORDER_CATALOG[start_index:end_index]
    
    # If there are more items left in the catalog, set the next cursor to the next index
    next_cursor = None
    if end_index < len(ORDER_CATALOG):
        next_cursor = str(end_index)
        
    return {
        "items": page_items,
        "next_cursor": next_cursor
    }


# ---------------------------------------------------------
# MIDDLEWARE: Per-Client Rate Limiting
# We intercept all requests *before* they hit endpoints to check the client bucket
# ---------------------------------------------------------
@app.middleware("http")
async def rate_limiter(request: Request, call_next):
    # Read the X-Client-Id header. Fallback to IP if missing.
    client_id = request.headers.get("X-Client-Id") or request.client.host
    
    # Don't rate limit the preflight OPTIONS requests from browsers
    if request.method == "OPTIONS":
        return await call_next(request)
        
    current_time = time.time()
    
    # Initialize the client's bucket if they are new
    if client_id not in rate_limit_db:
        rate_limit_db[client_id] = []
        
    # Sliding window: Clean up timestamps older than 10 seconds ago
    rate_limit_db[client_id] = [ts for ts in rate_limit_db[client_id] if current_time - ts < RATE_LIMIT_WINDOW]
    
    # Check if they have exceeded the limit
    if len(rate_limit_db[client_id]) >= RATE_LIMIT_MAX:
        # Calculate exactly how many seconds until the oldest request falls out of the window
        oldest_request = rate_limit_db[client_id][0]
        retry_after = max(1, int(RATE_LIMIT_WINDOW - (current_time - oldest_request)))
        
        # Block them with an HTTP 429 Too Many Requests
        return Response(
            content='{"detail": "Rate limit exceeded"}',
            status_code=429,
            media_type="application/json",
            headers={"Retry-After": str(retry_after), "Access-Control-Allow-Origin": "*"}
        )
        
    # If they are clear, log this request's timestamp and let them pass
    rate_limit_db[client_id].append(current_time)
    return await call_next(request)