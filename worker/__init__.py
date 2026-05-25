"""Out-of-process persistence worker.

The gateway streams the model's bytes to the client, then hands the finished
exchange off to this worker via a Redis-backed arq queue. The worker runs the
persist pipeline (``memory.persist.run_persist``) — entity extraction, vault
note write, JSONL log, metrics — so disk I/O never sits on the request path.

If Redis is unreachable the gateway runs the same pipeline inline, so nothing
is lost; the worker is an offload, not a single point of failure.
"""
