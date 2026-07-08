import time
import uuid
from fastapi import FastAPI, Request, Response, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

app = FastAPI()

# ---------------------------------------------------------
# THE BOUNCER (CORS Policy)
# expose_headers allows the grader to actually see the Retry-After header!
# ---------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"]
)

# ---------------------------------------------------------
# GLOBAL IN-MEMORY STORAGE
# ---------------------------------------------------------
TOTAL_ORDERS = 59  
RATE_LIMIT_MAX = 15  
RATE_LIMIT_WINDOW = 10.0  

ORDER_CATALOG = [{"id": i, "item": f"Item {i}", "price": round(10.5 * i, 2)} for i in range(1, TOTAL_ORDERS + 1)]

idempotency_db = {}  
rate_limit_db = {}   

# ---------------------------------------------------------
# ENDPOINT 1: Idempotent Order Creation
# ---------------------------------------------------------
@app.post("/orders", status_code=201)
def create_order(response: Response, idempotency_key: Optional[str] = Header(None)):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Missing Idempotency-Key header")
        
    if idempotency_key in idempotency_db:
        response.status_code = 200  
        return idempotency_db[idempotency_key]
        
    new_order = {
        "id": str(uuid.uuid4()),
        "status": "created",
        "created_at": time.time()
    }
    
    idempotency_db[idempotency_key] = new_order
    return new_order

# ---------------------------------------------------------
# ENDPOINT 2: Cursor Pagination
# ---------------------------------------------------------
@app.get("/orders")
def get_orders(limit: int = 10, cursor: Optional[str] = Query(None)):
    start_index = 0
    if cursor:
        try:
            start_index = int(cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cursor format")
            
    end_index = start_index + limit
    page_items = ORDER_CATALOG[start_index:end_index]
    
    next_cursor = None
    if end_index < len(ORDER_CATALOG):
        next_cursor = str(end_index)
        
    return {
        "items": page_items,
        "next_cursor": next_cursor
    }

# ---------------------------------------------------------
# MIDDLEWARE: Per-Client Rate Limiting
# ---------------------------------------------------------
@app.middleware("http")
async def rate_limiter(request: Request, call_next):
    client_id = request.headers.get("X-Client-Id") or request.client.host
    
    if request.method == "OPTIONS":
        return await call_next(request)
        
    current_time = time.time()
    
    if client_id not in rate_limit_db:
        rate_limit_db[client_id] = []
        
    rate_limit_db[client_id] = [ts for ts in rate_limit_db[client_id] if current_time - ts < RATE_LIMIT_WINDOW]
    
    if len(rate_limit_db[client_id]) >= RATE_LIMIT_MAX:
        oldest_request = rate_limit_db[client_id][0]
        retry_after = max(1, int(RATE_LIMIT_WINDOW - (current_time - oldest_request)))
        
        return Response(
            content='{"detail": "Rate limit exceeded"}',
            status_code=429,
            media_type="application/json",
            headers={
                "Retry-After": str(retry_after), 
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Expose-Headers": "Retry-After" # <-- We manually added the stamp here!
            }
        )
        
    rate_limit_db[client_id].append(current_time)
    return await call_next(request)
