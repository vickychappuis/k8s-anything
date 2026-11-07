import os

import redis
from flask import Flask

app = Flask(__name__)
r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


@app.get("/")
def index():
    return {"hits": r.incr("hits")}


@app.get("/healthz")
def healthz():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)))  # deliberate pitfall: localhost bind
