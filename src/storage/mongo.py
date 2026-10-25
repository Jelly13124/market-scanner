"""Lazy optional MongoDB connection with a process-wide circuit breaker.

Never log driver errors: their messages may contain connection credentials.
Schema installation is an explicit maintenance operation, not a startup side effect.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import date, datetime, timezone
from dataclasses import asdict, is_dataclass
from typing import Callable

logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc)


def json_value(value):
    if hasattr(value, 'model_dump'):
        return value.model_dump(mode='json')
    if is_dataclass(value):
        return {k: json_value(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        items = sorted(value) if isinstance(value, set) else value
        return [json_value(v) for v in items]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value.__class__.__name__ in ('ObjectId', 'Decimal128'):
        return str(value)
    return value


def digest(value):
    return hashlib.sha256(json.dumps(json_value(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class StorageUnavailable(RuntimeError):
    pass


class MongoStore:
    def __init__(self, database=None):
        self._db = database
        self._client = None
        self._retry_at = 0.0
        self._lock = threading.RLock()
        self.status = 'ready' if database is not None else 'unconfigured'

    def execute(self, operation: Callable, *, required=False):
        with self._lock:
            if time.monotonic() < self._retry_at:
                if required:
                    raise StorageUnavailable('MongoDB is temporarily unavailable')
                return None
            try:
                if self._db is None:
                    uri = os.getenv('MONGODB_URI', '').strip()
                    if not uri:
                        self.status = 'unconfigured'
                        if required:
                            raise StorageUnavailable('MongoDB is not configured')
                        return None
                    from pymongo import MongoClient
                    timeout = max(50, int(os.getenv('MONGODB_TIMEOUT_MS', '500')))
                    self._client = MongoClient(uri, serverSelectionTimeoutMS=timeout, connectTimeoutMS=timeout,
                                               socketTimeoutMS=timeout, tz_aware=True)
                    self._db = self._client[os.getenv('MONGODB_DATABASE', 'market_scanner')]
                result = operation(self._db)
                self.status = 'ready'
                return result
            except (StorageUnavailable, ValueError):
                raise
            except Exception:
                self.status = 'unavailable'
                self._retry_at = time.monotonic() + 30
                logger.warning('MongoDB unavailable; continuing without durable storage')
                if required:
                    raise StorageUnavailable('MongoDB operation failed') from None
                return None

    def instrument(self, ticker, db):
        from bson import ObjectId
        symbol = ticker.strip().upper()
        market = 'CN' if symbol.endswith(('.SH', '.SZ', '.BJ')) else 'US'
        exchange = {'SH': 'XSHG', 'SZ': 'XSHE', 'BJ': 'XBSE'}.get(symbol.rsplit('.', 1)[-1], 'XUNK')
        key = {'market': market, 'exchange': exchange, 'symbol': symbol}
        doc = dict(key, _id=ObjectId(), schema_version=1, name=symbol, asset_type='equity',
                   currency='CNY' if market == 'CN' else 'USD', timezone='Asia/Shanghai' if market == 'CN' else 'America/New_York',
                   provider_symbols={'yahoo': symbol}, active=True, created_at=utcnow())
        db.instruments.update_one(key, {'$setOnInsert': doc}, upsert=True)
        return db.instruments.find_one(key)['_id']

    def install_schema(self):
        from pathlib import Path
        from pymongo import IndexModel
        schema = json.loads((Path(__file__).resolve().parents[2] / 'docs/design/mongodb-schema.json').read_text())
        def install(db):
            existing = db.list_collection_names()
            for name, spec in schema['collections'].items():
                options = {k: spec[k] for k in ('validator', 'validationLevel', 'validationAction')}
                if name not in existing:
                    db.create_collection(name, **options)
                else:
                    db.command('collMod', name, **options)
                for index in spec.get('indexes', []):
                    if index.get('name') == '_id_':
                        continue
                    keys = list(index.get('key', index.get('keys', {})).items())
                    opts = {k: v for k, v in index.items() if k not in ('key', 'keys', 'description')}
                    db[name].create_indexes([IndexModel(keys, **opts)])
            return True
        return self.execute(install, required=True)


_STORE = MongoStore()


def get_store():
    return _STORE
