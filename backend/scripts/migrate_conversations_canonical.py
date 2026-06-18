"""
Canonical conversation migration — Batch 16F-E
===============================================

Merges legacy conversation documents (per-listing, per-reel, old underscore-format)
into one canonical conv_v1_{sha256} document per user pair.

Background
----------
Batch 16F-D changed _conversation_id() to return conv_{uid_a}_{uid_b}.
Batch 16F-E changes it to conv_v1_{sha256(json(sorted_pair))}.

This script handles two migration scenarios:

  Scenario A — per-listing / per-reel legacy documents
    conv_{a}_{b}_marketplace_{listing_id}
    conv_{a}_{b}_{reel_id}
    conv_{a}_{b}_general

  Scenario B — old underscore-format canonical (16F-D)
    conv_{uid_a}_{uid_b}  →  conv_v1_{sha256}

After migration each canonical conv_v1_{sha256} document is the single source
of truth.  Legacy documents are marked status=merged + merged_into=<canonical>.

Safety
------
* Messages are COPIED, never deleted. Legacy documents are only marked merged.
* Message IDs are deduplicated using sha256(legacy_conv_id + ':' + legacy_msg_id)
  to prevent collisions when the same message_id string appears in multiple legacy docs.
* Run --dry-run first. --apply is idempotent (safe to re-run).
* Supports --limit N and --resume <checkpoint_id> for staged production rollout.
* Writes a run report to stdout and optionally to --report-file.

Usage
-----
  # Dry-run (inspect only, no writes)
  python scripts/migrate_conversations_canonical.py --dry-run

  # Staged apply (100 pairs at a time)
  python scripts/migrate_conversations_canonical.py --apply --limit 100

  # Resume from a stored checkpoint
  python scripts/migrate_conversations_canonical.py --apply --limit 100 --resume <last_pair_key>

  # Save report to file
  python scripts/migrate_conversations_canonical.py --dry-run --report-file report.txt
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from io import StringIO

# ---------------------------------------------------------------------------
# Bootstrap: add backend root to sys.path
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, BACKEND_DIR)

from core.firebase import db  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger('migrate_canonical')

CONVERSATIONS = 'conversations'
MESSAGES = 'chat_messages'
MIGRATION_VERSION = '16fe'


# ---------------------------------------------------------------------------
# Canonical ID computation (must match message_repository._conversation_id)
# ---------------------------------------------------------------------------

def _pair_hash(uid_a: str, uid_b: str) -> str:
    pair = sorted([uid_a, uid_b])
    payload = json.dumps(pair, ensure_ascii=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _canonical_id(uid_a: str, uid_b: str) -> str:
    return f'conv_v1_{_pair_hash(uid_a, uid_b)}'


def _old_canonical_id(uid_a: str, uid_b: str) -> str:
    a, b = sorted([uid_a, uid_b])
    return f'conv_{a}_{b}'


def _sorted_pair(participants: list) -> tuple[str, str] | None:
    """Return (uid_a, uid_b) if participants is a valid 2-user list, else None."""
    ids = [str(p).strip() for p in (participants or []) if str(p).strip()]
    unique = list(dict.fromkeys(ids))  # deduplicate preserving order
    if len(unique) != 2:
        return None
    return tuple(sorted(unique))  # type: ignore[return-value]


def _migrated_message_id(legacy_conv_id: str, legacy_msg_id: str) -> str:
    """Deterministic stable ID for a migrated message.

    Using a hash of the origin tuple prevents collisions when the same
    message_id string appears in multiple legacy conversation documents.
    The original ID is preserved in origin_message_id for traceability.
    """
    raw = f'{MIGRATION_VERSION}:{legacy_conv_id}:{legacy_msg_id}'
    h = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]
    return f'mmsg_{h}'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def scan_conversations() -> dict[tuple, list[dict]]:
    """Scan all conversations and group by canonical (uid_a, uid_b) pair.

    Returns {(uid_a, uid_b): [conv_dict, ...]} for all pairs.
    Skips and logs malformed / self-conversation documents.
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    total = skipped = 0

    for doc in db.collection(CONVERSATIONS).stream():
        data = doc.to_dict() or {}
        data['id'] = data.get('id') or doc.id
        pair = _sorted_pair(data.get('participants'))
        if pair is None:
            logger.debug('Skipping malformed doc %s (participants=%s)', doc.id, data.get('participants'))
            skipped += 1
            continue
        groups[pair].append(data)
        total += 1

    logger.info('Scanned %d docs, %d malformed/skipped, %d valid pairs.', total, skipped, len(groups))
    return dict(groups)


# ---------------------------------------------------------------------------
# Classify
# ---------------------------------------------------------------------------

def classify(groups: dict) -> tuple[list, list]:
    """Return (pairs_needing_migration, pairs_already_ok)."""
    need = []
    ok = []

    for pair, convs in groups.items():
        uid_a, uid_b = pair
        canonical = _canonical_id(uid_a, uid_b)
        active = [c for c in convs if c.get('status') != 'merged']

        has_v1_canonical = any(c['id'] == canonical for c in active)
        non_canonical = [c for c in active if c['id'] != canonical]

        if has_v1_canonical and not non_canonical:
            ok.append((pair, convs))
        elif len(active) == 1 and not has_v1_canonical:
            # Single active doc but in old format — still needs v1 canonical creation
            old_can = _old_canonical_id(uid_a, uid_b)
            if active[0]['id'] == old_can or active[0]['id'].startswith(f'conv_{uid_a}_') or \
               active[0]['id'].startswith(f'conv_{uid_b}_'):
                need.append((pair, convs))
            else:
                ok.append((pair, convs))
        elif len(active) > 1 or (len(active) == 1 and not has_v1_canonical):
            need.append((pair, convs))
        else:
            ok.append((pair, convs))

    return need, ok


# ---------------------------------------------------------------------------
# Dry-run report
# ---------------------------------------------------------------------------

def dry_run(groups: dict, report_file: str | None = None) -> None:
    need, ok = classify(groups)
    buf = StringIO()

    def out(msg: str = '') -> None:
        print(msg, file=buf)

    run_id = uuid.uuid4().hex[:12]
    out(f'\n{"="*64}')
    out(f'DRY RUN  run_id={run_id}  {_now()}')
    out(f'{"="*64}')
    out(f'Total pairs              : {len(groups)}')
    out(f'Pairs already canonical  : {len(ok)}')
    out(f'Pairs needing migration  : {len(need)}')
    out()

    total_msgs = 0
    for pair, convs in need[:50]:
        uid_a, uid_b = pair
        canonical = _canonical_id(uid_a, uid_b)
        active = [c for c in convs if c.get('status') != 'merged']
        has_v1 = any(c['id'] == canonical for c in active)
        legacy = [c for c in active if c['id'] != canonical]

        msg_count = 0
        for c in legacy:
            try:
                msg_count += len(list(
                    db.collection(MESSAGES).where('conversation_id', '==', c['id']).stream()
                ))
            except Exception:
                pass
        total_msgs += msg_count

        out(f'  Pair {uid_a[:8]}…/{uid_b[:8]}…')
        out(f'    v1 canonical         : {canonical}')
        out(f'    v1 canonical exists  : {has_v1}')
        out(f'    Legacy convs         : {len(legacy)}')
        for c in legacy:
            ctx = c.get('listing_id') or c.get('reel_id') or 'direct'
            out(f'      {c["id"]}  (ctx={ctx})')
        out(f'    Messages to migrate  : {msg_count}')
        out()

    if len(need) > 50:
        out(f'  … and {len(need) - 50} more pairs (output truncated)')

    out(f'Total legacy messages to migrate: {total_msgs}')
    out()
    out('Run with --apply to execute.  Use --limit N and --resume KEY for staged rollout.')

    report = buf.getvalue()
    print(report)
    if report_file:
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        logger.info('Report written to %s', report_file)


# ---------------------------------------------------------------------------
# Apply migration for one pair
# ---------------------------------------------------------------------------

def migrate_pair(pair: tuple, convs: list[dict], dry: bool = False) -> dict:
    uid_a, uid_b = pair
    canonical = _canonical_id(uid_a, uid_b)
    old_can = _old_canonical_id(uid_a, uid_b)
    now = _now()

    active = [c for c in convs if c.get('status') != 'merged']
    v1_conv = next((c for c in active if c['id'] == canonical), None)
    legacy_convs = [c for c in active if c['id'] != canonical]

    if not legacy_convs:
        return {'pair': pair, 'skipped': True, 'reason': 'no_legacy'}

    # ------ Resolve / create canonical document ------
    if v1_conv is None:
        # Pick the richest legacy doc as the template
        template = sorted(
            legacy_convs,
            key=lambda c: (
                1 if c.get('listing_id') else 0,
                str(c.get('last_message_at') or ''),
            ),
            reverse=True,
        )[0]

        new_canonical = dict(template)
        new_canonical['id'] = canonical
        new_canonical['pair_hash'] = _pair_hash(uid_a, uid_b)
        new_canonical['pair_key_version'] = 1
        new_canonical['migration_version'] = MIGRATION_VERSION
        new_canonical['updated_at'] = now
        new_canonical['migration_done'] = True
        # Ensure participants are sorted
        new_canonical['participants'] = sorted([uid_a, uid_b])

        if not dry:
            db.collection(CONVERSATIONS).document(canonical).set(new_canonical, merge=True)
        logger.info('[%s] Created v1 canonical conversation.', canonical)
    else:
        if not dry:
            db.collection(CONVERSATIONS).document(canonical).set(
                {'migration_done': True, 'migration_version': MIGRATION_VERSION, 'updated_at': now},
                merge=True,
            )

    # ------ Collect already-migrated message origin IDs (idempotency) ------
    seen_origins: set[str] = set()
    if not dry:
        for msg_doc in db.collection(MESSAGES).where('conversation_id', '==', canonical).stream():
            md = msg_doc.to_dict() or {}
            origin = md.get('origin_message_id') or md.get('id') or msg_doc.id
            seen_origins.add(origin)

    # ------ Migrate messages from each legacy doc ------
    messages_migrated = 0
    messages_skipped = 0
    ordering_warnings = 0
    errors: list[str] = []

    for legacy in legacy_convs:
        legacy_id = legacy['id']

        # Derive context backfill from legacy conversation fields
        ctx_type = ctx_id = ctx_title = ctx_thumb = ctx_currency = ''
        ctx_price = None
        if legacy.get('listing_id'):
            ctx_type = 'marketplace_listing'
            ctx_id = str(legacy['listing_id'])
            ctx_title = str(legacy.get('listing_title') or '')
            ctx_thumb = str(legacy.get('listing_image') or '')
            ctx_price = float(legacy.get('listing_price') or 0) or None
            ctx_currency = str(legacy.get('listing_currency') or '')
        elif legacy.get('reel_id'):
            ctx_type = 'reel'
            ctx_id = str(legacy['reel_id'])
            ctx_title = str(legacy.get('reel_title') or '')
            ctx_thumb = str(legacy.get('reel_thumbnail_url') or '')

        try:
            msg_docs = list(
                db.collection(MESSAGES).where('conversation_id', '==', legacy_id).stream()
            )
        except Exception as exc:
            errors.append(f'list_messages legacy_id={legacy_id} error={exc}')
            continue

        # Sort by created_at for stable ordering; warn on ties or missing timestamps
        def _msg_sort_key(d: dict) -> tuple:
            ts = d.get('created_at') or ''
            orig_id = d.get('id') or ''
            return (str(ts), orig_id)  # stable tie-break by message ID

        msg_list = [d.to_dict() or {} for d in msg_docs]
        for md in msg_list:
            if not md.get('created_at'):
                ordering_warnings += 1

        msg_list.sort(key=_msg_sort_key)

        for md in msg_list:
            original_msg_id = md.get('id') or ''
            origin_key = f'{legacy_id}:{original_msg_id}'

            if origin_key in seen_origins or original_msg_id in seen_origins:
                messages_skipped += 1
                continue

            # Stable migrated message ID derived from origin tuple
            new_msg_id = _migrated_message_id(legacy_id, original_msg_id)

            new_msg = dict(md)
            new_msg['id'] = new_msg_id
            new_msg['conversation_id'] = canonical
            new_msg['origin_message_id'] = original_msg_id
            new_msg['origin_conversation_id'] = legacy_id
            new_msg['migration_version'] = MIGRATION_VERSION

            # Backfill context fields for pre-context-schema messages
            if not new_msg.get('context_type') and ctx_type:
                new_msg['context_type'] = ctx_type
                new_msg['context_id'] = ctx_id
                new_msg['context_title'] = ctx_title
                new_msg['context_thumbnail_url'] = ctx_thumb
                new_msg['context_price'] = ctx_price
                new_msg['context_currency'] = ctx_currency

            if not dry:
                db.collection(MESSAGES).document(new_msg_id).set(new_msg, merge=True)

            seen_origins.add(origin_key)
            seen_origins.add(original_msg_id)
            messages_migrated += 1

        logger.info(
            '[%s] Legacy %s → migrated %d messages.',
            canonical, legacy_id, messages_migrated,
        )

        # Mark legacy as merged only after messages are copied
        if not dry:
            db.collection(CONVERSATIONS).document(legacy_id).set(
                {
                    'status': 'merged',
                    'merged_into': canonical,
                    'merged_at': now,
                    'migration_version': MIGRATION_VERSION,
                    'updated_at': now,
                },
                merge=True,
            )

    # ------ Count parity check ------
    count_parity_ok = True
    if not dry:
        canonical_count = len(list(
            db.collection(MESSAGES).where('conversation_id', '==', canonical).stream()
        ))
        expected_min = messages_migrated
        if canonical_count < expected_min:
            count_parity_ok = False
            errors.append(
                f'count_parity FAIL canonical_count={canonical_count} expected_min={expected_min}'
            )

    return {
        'pair': pair,
        'canonical_id': canonical,
        'legacy_count': len(legacy_convs),
        'messages_migrated': messages_migrated,
        'messages_skipped': messages_skipped,
        'ordering_warnings': ordering_warnings,
        'count_parity_ok': count_parity_ok,
        'errors': errors,
    }


# ---------------------------------------------------------------------------
# Apply all
# ---------------------------------------------------------------------------

def apply_migration(
    groups: dict,
    limit: int | None = None,
    resume: str | None = None,
    report_file: str | None = None,
) -> None:
    need, _ = classify(groups)

    # Apply resume checkpoint: skip pairs whose key <= resume
    if resume:
        need = [item for item in need if '_'.join(str(x) for x in item[0]) > resume]

    if limit:
        need = need[:limit]

    run_id = uuid.uuid4().hex[:12]
    print(f'\nApply run_id={run_id}  {_now()}')
    print(f'Processing {len(need)} pairs ...\n')

    results = []
    last_pair_key = None

    for i, (pair, convs) in enumerate(need, 1):
        pair_key = '_'.join(pair)
        try:
            result = migrate_pair(pair, convs, dry=False)
            results.append(result)
            last_pair_key = pair_key
            logger.info(
                '[%d/%d] %s — migrated %d msgs, merged %d legacy convs%s',
                i, len(need),
                result.get('canonical_id', '?'),
                result.get('messages_migrated', 0),
                result.get('legacy_count', 0),
                ' PARITY_FAIL' if not result.get('count_parity_ok', True) else '',
            )
        except Exception as exc:
            logger.error('[%d/%d] FAILED pair=%s error=%s', i, len(need), pair, exc)

    total_migrated = sum(r.get('messages_migrated', 0) for r in results)
    total_skipped = sum(r.get('messages_skipped', 0) for r in results)
    total_merged = sum(r.get('legacy_count', 0) for r in results)
    total_warn = sum(r.get('ordering_warnings', 0) for r in results)
    parity_fails = sum(1 for r in results if not r.get('count_parity_ok', True))
    all_errors = [e for r in results for e in r.get('errors', [])]

    buf = StringIO()
    def out(msg=''):
        print(msg, file=buf)

    out(f'\n{"="*64}')
    out(f'Migration complete  run_id={run_id}  {_now()}')
    out(f'{"="*64}')
    out(f'  Pairs processed      : {len(results)}')
    out(f'  Legacy convs merged  : {total_merged}')
    out(f'  Messages migrated    : {total_migrated}')
    out(f'  Messages skipped     : {total_skipped} (already present)')
    out(f'  Ordering warnings    : {total_warn}')
    out(f'  Parity failures      : {parity_fails}')
    out(f'  Errors               : {len(all_errors)}')
    if all_errors:
        out()
        out('  Error details:')
        for e in all_errors[:20]:
            out(f'    {e}')
    if last_pair_key:
        out()
        out(f'  Checkpoint (--resume): {last_pair_key}')
    out()
    out('Verify: re-run --dry-run and confirm "Pairs needing migration: 0"')

    report = buf.getvalue()
    print(report)
    if report_file:
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description='Migrate conversations to canonical v1 (SHA-256) IDs')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--dry-run', action='store_true', help='Inspect only, no writes')
    group.add_argument('--apply', action='store_true', help='Apply migration')
    parser.add_argument('--limit', type=int, default=None, help='Max pairs to process')
    parser.add_argument('--resume', type=str, default=None, help='Skip pairs up to and including this checkpoint key')
    parser.add_argument('--report-file', type=str, default=None, help='Save report to this file path')
    args = parser.parse_args()

    logger.info('Scanning Firestore conversations ...')
    groups = scan_conversations()

    if args.dry_run:
        dry_run(groups, report_file=args.report_file)
    else:
        apply_migration(groups, limit=args.limit, resume=args.resume, report_file=args.report_file)


if __name__ == '__main__':
    main()
