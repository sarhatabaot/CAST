"""Small mutual-exclusion helper built on Django's shared cache.

In production the cache is Redis (see CACHE_BACKEND), so ``cache.add`` is an atomic
``SET key value NX EX`` — only one caller across all processes/containers can hold a
given key. The TTL guarantees a crashed holder's lock is eventually reclaimed, so a
job can never wedge permanently.
"""
from __future__ import annotations

import contextlib
import logging
import uuid

from django.core.cache import cache

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def redis_lock(key: str, timeout: int):
    """Best-effort exclusive lock; yields True if acquired, False if already held.

    Usage::

        with redis_lock("ingest:lock", 1800) as acquired:
            if not acquired:
                return  # someone else is running
            ...

    Released on exit only if we still own our token, so an expired-and-reacquired
    lock owned by another run is never deleted out from under it.
    """
    token = uuid.uuid4().hex
    acquired = bool(cache.add(key, token, timeout=timeout))
    try:
        yield acquired
    finally:
        if acquired:
            try:
                if cache.get(key) == token:
                    cache.delete(key)
            except Exception as e:  # releasing is best-effort; TTL is the real backstop
                logger.warning("Failed to release lock %s: %s", key, e)
