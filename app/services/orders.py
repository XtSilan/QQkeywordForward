"""Order-fingerprint dedup for keyword alert messages.

Port-logistics group messages carry one or more cargo "orders" (date +
destination + box type + tonnage + contact phone). The same order is reposted
across dozens of groups, so instead of deduplicating raw message text (or
cooling down senders) each message is parsed into order candidates and
deduplicated per order on a sliding window:

- same (dest, day, box, weight) with similar core text  -> same order
- shared phone number with moderately similar core text -> same order
- undelivered orders (sent_at NULL) may always re-enqueue on a repost
- delivered orders accept one supplementary push for a new contact phone
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.repositories import meta_repo

PHONE_RE = re.compile(r"1[3-9]\d{9}")
DATE_WORDS = "明天|后天|今天|现在"
DATE_RE = re.compile(DATE_WORDS)
# Split before each date word (except the 天 in 今天/明天/后天 preceded by +,
# e.g. "明天+后天") and after arrival-time markers.
SPLIT_RE = re.compile(
    rf"(?<![天+])(?=(?:{DATE_WORDS}))|(?<=中午到)|(?<=一早到)|(?<=下午到)"
)
BOX_RE = re.compile(r"[大小对高]柜")
WEIGHT_RE = re.compile(r"(\d+(?:\.\d+)?)(?:t|吨|/个)")
CORE_STRIP_RE = re.compile(
    rf"[^\w一-鿿]|{DATE_WORDS}|现金|联系|加微信|一早|中午到|下午到"
)
PERIOD_RE = re.compile(r"([1-5])期")
PHONE_SIM_FLOOR = 0.6
SHORT_CORE_EXACT_LEN = 6
DEFAULT_AD_KEYWORDS = ("招工", "日结", "时薪", "暑假工")

META_KEYS = {
    "enabled": "alert_dedup_enabled",
    "similarity": "alert_similarity_threshold",
    "window_minutes": "alert_order_window_minutes",
    "max_push": "alert_max_push_per_order",
    "new_phone_repush": "alert_new_phone_repush",
    "ad_filter_enabled": "alert_ad_filter_enabled",
    "ad_keywords": "alert_ad_keywords",
}


@dataclass
class DedupSettings:
    enabled: bool = True
    similarity: float = 0.8
    window_seconds: float = 3600.0
    max_push: int = 2
    new_phone_repush: bool = True
    ad_filter_enabled: bool = True
    ad_keywords: tuple[str, ...] = DEFAULT_AD_KEYWORDS


@dataclass
class OrderCandidate:
    dest: str
    day: str
    box: str
    wt: str
    core: str
    phones: set[str] = field(default_factory=set)
    text: str = ""


def load_settings(conn) -> DedupSettings:
    values = meta_repo.get_by_prefix(conn, "alert_")

    def _float(key: str, default: float) -> float:
        try:
            return float(values.get(key, str(default)))
        except ValueError:
            return default

    def _int(key: str, default: int) -> int:
        try:
            return int(values.get(key, str(default)))
        except ValueError:
            return default

    ad_keywords = tuple(
        kw.strip()
        for kw in values.get(META_KEYS["ad_keywords"], ",".join(DEFAULT_AD_KEYWORDS)).split(",")
        if kw.strip()
    )
    return DedupSettings(
        enabled=values.get(META_KEYS["enabled"], "1") == "1",
        similarity=_float(META_KEYS["similarity"], 0.8),
        window_seconds=max(60.0, _float(META_KEYS["window_minutes"], 60.0) * 60.0),
        max_push=max(1, _int(META_KEYS["max_push"], 2)),
        new_phone_repush=values.get(META_KEYS["new_phone_repush"], "1") == "1",
        ad_filter_enabled=values.get(META_KEYS["ad_filter_enabled"], "1") == "1",
        ad_keywords=ad_keywords or DEFAULT_AD_KEYWORDS,
    )


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(
        ch
        for ch in normalized
        if not ch.isspace() and unicodedata.category(ch) != "Cf"
    )


def _fold_self_duplication(s: str) -> str:
    """Messages are often posted with the body duplicated verbatim; fold t+t -> t."""
    half, rem = divmod(len(s), 2)
    if rem == 0 and half > 0 and s[:half] == s[half:]:
        return s[:half]
    return s


def _resolve_day(offset: int, now: float) -> str:
    """Absolute cargo date; 今天/现在 share offset 0 so evening 明天 and
    next-morning 今天 posts of the same cargo land on the same day."""
    return str(date.fromtimestamp(now) + timedelta(days=offset))


def parse(
    text: str, lexicon: list[str], now: float, settings: DedupSettings
) -> list[OrderCandidate]:
    """Clean -> ad filter -> split into per-order segments -> keep segments
    that contain at least one keyword from the lexicon."""
    s = _fold_self_duplication(_normalize(text))
    if settings.ad_filter_enabled and any(kw in s for kw in settings.ad_keywords):
        return []
    keywords = [kw.casefold().strip() for kw in lexicon if kw and kw.strip()]
    msg_phones = set(PHONE_RE.findall(s))
    candidates: list[OrderCandidate] = []
    offset = 0
    for seg in SPLIT_RE.split(s):
        if not seg:
            continue
        date_match = DATE_RE.match(seg)
        if date_match:
            offset = {"明天": 1, "后天": 2}.get(date_match.group(0), 0)
        dests = sorted({kw for kw in keywords if kw in seg})
        if not dests:
            continue
        body = PHONE_RE.sub("", seg)
        core = CORE_STRIP_RE.sub("", body)
        core = PERIOD_RE.sub(
            lambda m: "一二三四五"[int(m.group(1)) - 1] + "期", core
        )
        box_match = BOX_RE.search(body)
        weight_match = WEIGHT_RE.search(body)
        candidates.append(
            OrderCandidate(
                dest="|".join(dests),
                day=_resolve_day(offset, now),
                box=box_match.group(0) if box_match else "",
                wt=weight_match.group(1) if weight_match else "",
                core=core,
                phones=set(PHONE_RE.findall(seg)) or msg_phones,
                text=seg,
            )
        )
    return candidates


def sim(a: str, b: str) -> float:
    """Character 2-gram Jaccard similarity."""
    if len(a) < 2 or len(b) < 2:
        return 0.0
    grams_a = {a[i : i + 2] for i in range(len(a) - 1)}
    grams_b = {b[i : i + 2] for i in range(len(b) - 1)}
    return len(grams_a & grams_b) / max(1, len(grams_a | grams_b))


def fingerprint(cand: OrderCandidate) -> str:
    raw = cand.day + cand.core + cand.box + cand.wt
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _phones_of(raw: object) -> set[str]:
    return set(filter(None, str(raw or "").split(",")))


def _same_order(row, cand: OrderCandidate, threshold: float) -> bool:
    similarity = sim(str(row["core"]), cand.core)
    if row["box"] == cand.box and row["wt"] == cand.wt and similarity >= threshold:
        return True
    if _phones_of(row["phones"]) & cand.phones and similarity >= PHONE_SIM_FLOOR:
        return True
    if len(cand.core) < SHORT_CORE_EXACT_LEN and row["core"] == cand.core:
        return True
    return False


def decide(conn, cand: OrderCandidate, now: float, settings: DedupSettings) -> tuple[str, str]:
    """Return (fp, 'push'|'drop'). New orders and undelivered orders push;
    delivered orders slide the window and only push for a new contact phone."""
    rows = conn.execute(
        "SELECT * FROM orders WHERE dest=? AND day=?", (cand.dest, cand.day)
    ).fetchall()
    match = None
    for row in rows:
        if _same_order(row, cand, settings.similarity):
            match = row
            break
    if match is None:
        fp = fingerprint(cand)
        conn.execute(
            "INSERT OR IGNORE INTO orders(fp, dest, day, box, wt, core, phones, last_seen, text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fp,
                cand.dest,
                cand.day,
                cand.box,
                cand.wt,
                cand.core,
                ",".join(sorted(cand.phones)),
                now,
                cand.text,
            ),
        )
        return fp, "push"

    fp = str(match["fp"])
    if match["sent_at"] is None:
        return fp, "push"
    if now - float(match["last_seen"]) > settings.window_seconds:
        conn.execute(
            "UPDATE orders SET last_seen=?, sent_at=NULL, n_push=0, phones=? WHERE fp=?",
            (now, ",".join(sorted(cand.phones)), fp),
        )
        return fp, "push"
    known = _phones_of(match["phones"])
    conn.execute(
        "UPDATE orders SET last_seen=?, phones=? WHERE fp=?",
        (now, ",".join(sorted(known | cand.phones)), fp),
    )
    if (
        cand.phones - known
        and settings.new_phone_repush
        and int(match["n_push"]) < settings.max_push
    ):
        return fp, "push"
    return fp, "drop"


def mark_sent(conn, fp: str, now: float) -> None:
    """Record a successful enqueue/delivery for the order."""
    conn.execute(
        "UPDATE orders SET sent_at=?, n_push=n_push+1 WHERE fp=?", (now, fp)
    )
