"""LangGraph checkpoint adapter with optional MongoDB durability.

State contains section outputs only. API keys live in run-local closures and
never enter this saver. No pickle fallback is enabled.
"""
from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple, WRITES_IDX_MAP
from langgraph.checkpoint.memory import MemorySaver
from src.storage.mongo import get_store, digest


class SectionSerializer:
    """JSON with a fixed value-type allowlist; never imports saved class names."""
    def dumps_typed(self, value):
        import json, base64
        from datetime import date, datetime
        from decimal import Decimal
        from dataclasses import asdict
        from src.research.models import SectionPayload
        def encode(item):
            if isinstance(item, SectionPayload):
                return {'__checkpoint_type__': 'section', 'value': asdict(item)}
            if isinstance(item, (date, datetime)):
                return {'__checkpoint_type__': 'datetime' if isinstance(item, datetime) else 'date', 'value': item.isoformat()}
            if isinstance(item, bytes):
                return {'__checkpoint_type__': 'bytes', 'value': base64.b64encode(item).decode()}
            if isinstance(item, set):
                return {'__checkpoint_type__': 'set', 'value': sorted(item)}
            if isinstance(item, Decimal):
                return float(item)
            raise TypeError('Unsupported checkpoint value type: ' + type(item).__name__)
        return 'json', json.dumps(value, default=encode, ensure_ascii=False, allow_nan=False).encode()

    def loads_typed(self, data):
        import json, base64
        from datetime import date, datetime
        from src.research.models import SectionPayload
        if data[0] != 'json':
            raise ValueError('Unsupported checkpoint encoding')
        def decode(item):
            if set(item) != {'__checkpoint_type__', 'value'}:
                return item
            kind, value = item['__checkpoint_type__'], item['value']
            if kind == 'section':
                return SectionPayload(**value)
            if kind == 'bytes':
                return base64.b64decode(value, validate=True)
            if kind == 'date':
                return date.fromisoformat(value)
            if kind == 'datetime':
                return datetime.fromisoformat(value)
            if kind == 'set':
                return set(value)
            raise ValueError('Unsupported checkpoint value tag')
        return json.loads(data[1], object_hook=decode)


class OptionalMongoSaver(BaseCheckpointSaver):
    def __init__(self, store=None):
        serializer = SectionSerializer()
        super().__init__(serde=serializer)
        self.store = store if store is not None else get_store()
        self.memory = MemorySaver(serde=serializer)

    @staticmethod
    def _query(config):
        c = config['configurable']
        q = {'thread_id': c['thread_id'], 'checkpoint_ns': c.get('checkpoint_ns', '')}
        if c.get('checkpoint_id'):
            q['checkpoint_id'] = c['checkpoint_id']
        return q

    def get_tuple(self, config):
        def get(db):
            row = db.langgraph_checkpoints.find_one(self._query(config), sort=[('checkpoint_id', -1)])
            if row is None:
                return None
            c = {'configurable': {'thread_id': row['thread_id'], 'checkpoint_ns': row['checkpoint_ns'],
                                  'checkpoint_id': row['checkpoint_id']}}
            query = self._query(c)
            writes = [(w['task_id'], w['channel'], self.serde.loads_typed(tuple(w['value'])))
                      for w in db.langgraph_writes.find(query).sort('index', 1)]
            return CheckpointTuple(config=c, checkpoint=self.serde.loads_typed(tuple(row['checkpoint'])),
                metadata=self.serde.loads_typed(tuple(row['metadata'])), parent_config=row.get('parent'), pending_writes=writes)
        return self.store.execute(get) or self.memory.get_tuple(config)

    def put(self, config, checkpoint, metadata, new_versions):
        result = self.memory.put(config, checkpoint, metadata, new_versions)
        q = self._query(result)
        row = dict(q, _id=digest(q), checkpoint=list(self.serde.dumps_typed(checkpoint)),
                   metadata=list(self.serde.dumps_typed(metadata)), parent=config)
        self.store.execute(lambda db: db.langgraph_checkpoints.update_one({'_id': row['_id']}, {'$setOnInsert': row}, upsert=True))
        return result

    def put_writes(self, config, writes, task_id, task_path=''):
        self.memory.put_writes(config, writes, task_id, task_path)
        def save(db):
            for i, (channel, value) in enumerate(writes):
                index = WRITES_IDX_MAP.get(channel, i)
                row = dict(self._query(config), task_id=task_id, index=index, channel=channel,
                           value=list(self.serde.dumps_typed(value)))
                row['_id'] = digest([self._query(config), task_id, index])
                db.langgraph_writes.update_one({'_id': row['_id']}, {'$set' if index < 0 else '$setOnInsert': row}, upsert=True)
        self.store.execute(save)

    def list(self, config, *, filter=None, before=None, limit=None):
        # Public application code uses owner-qualified thread ids; do not offer
        # a cross-owner global listing through this internal adapter.
        if config is None:
            return
        query = self._query(config)
        if before:
            query['checkpoint_id'] = {'$lt': before['configurable']['checkpoint_id']}
        rows = self.store.execute(lambda db: list(db.langgraph_checkpoints.find(query).sort('checkpoint_id', -1).limit(limit or 100)))
        if rows is None:
            yield from self.memory.list(config, filter=filter, before=before, limit=limit)
        else:
            for row in rows:
                current = {'configurable': {k: row[k] for k in ('thread_id', 'checkpoint_ns', 'checkpoint_id')}}
                value = self.get_tuple(current)
                if value and (not filter or all(value.metadata.get(k) == v for k, v in filter.items())):
                    yield value
