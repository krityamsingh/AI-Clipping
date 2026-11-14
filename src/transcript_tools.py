"""Transcript correction and safe multi-shot subtitle timing.

Lexical corrections must come from an explicit mapping. Timestamps are
preserved when possible and marked estimated after phrase changes.
"""
import math
import re
from copy import deepcopy


def _tokens(value):
    return [part for part in re.split(r"\s+", str(value).strip()) if part]


def correct_transcript(segments, replacements=None):
    replacements = replacements or {}
    if not isinstance(replacements, dict):
        raise ValueError("Caption corrections must be a JSON object")
    rules = []
    for bad, good in replacements.items():
        old, new = _tokens(bad), _tokens(good)
        if not old or not new:
            raise ValueError("Empty caption corrections are not allowed")
        rules.append((old, new))
    rules.sort(key=lambda pair: len(pair[0]), reverse=True)
    corrected = []
    for segment in segments:
        seg = deepcopy(segment)
        words = seg.get("words") or []
        if words:
            fixed_words = []
            i = 0
            while i < len(words):
                rule = next(((old, new) for old, new in rules
                             if len(words[i:i + len(old)]) == len(old)
                             and [str(w.get("word", "")).strip(" \t.,!?;:").casefold()
                                  for w in words[i:i + len(old)]]
                             == [w.strip(" \t.,!?;:").casefold() for w in old]), None)
                if rule is None:
                    fixed_words.append(dict(words[i]))
                    i += 1
                    continue
                old, new = rule
                start = float(words[i]["start"])
                end = float(words[i + len(old) - 1]["end"])
                if end <= start:
                    fixed_words.extend(dict(w) for w in words[i:i + len(old)])
                    i += len(old)
                    continue
                for n, token in enumerate(new):
                    fixed_words.append({
                        "word": token,
                        "start": round(start + (end - start) * n / len(new), 3),
                        "end": round(start + (end - start) * (n + 1) / len(new), 3),
                        "timing_estimated": len(old) != len(new),
                        "correction_applied": True
                    })
                i += len(old)
            seg["words"] = fixed_words
            seg["text"] = " ".join(str(w["word"]).strip() for w in fixed_words)
        else:
            text = str(seg.get("text") or "")
            for old, new in rules:
                pattern = r"(?<!\w)" + r"\s+".join(re.escape(t) for t in old) + r"(?!\w)"
                text = re.sub(pattern, " ".join(new), text, flags=re.IGNORECASE)
            seg["text"] = text.strip()
        corrected.append(seg)
    return corrected


def review_transcript(segments, confidence_threshold=0.55):
    flags = []
    for idx, segment in enumerate(segments):
        for word in segment.get("words") or []:
            probability = word.get("probability")
            if probability is not None and probability < confidence_threshold:
                flags.append({"segment": idx, "start": word.get("start"),
                              "end": word.get("end"), "word": word.get("word"),
                              "reason": "low_confidence", "probability": probability})
            if word.get("timing_estimated"):
                flags.append({"segment": idx, "start": word.get("start"),
                              "end": word.get("end"), "word": word.get("word"),
                              "reason": "estimated_word_timing"})
    return flags


def retime_shots(shots, transcript, durations=None):
    """Map speech into the assembled timeline, including discontinuous edits."""
    result = []
    offset = 0.0
    for idx, shot in enumerate(shots):
        start, end = float(shot["source_start"]), float(shot["source_end"])
        actual_length = float(durations[idx]) if durations is not None else end - start
        if not math.isfinite(actual_length) or actual_length <= 0:
            raise ValueError("Invalid rendered shot duration")
        for segment in transcript:
            seg_start, seg_end = float(segment["start"]), float(segment["end"])
            if seg_end <= start or seg_start >= end:
                continue
            words = segment.get("words") or []
            if words:
                included = []
                for word in words:
                    ws, we = float(word["start"]), float(word["end"])
                    if we <= start or ws >= end:
                        continue
                    new_start = max(0.0, ws - start)
                    new_end = min(actual_length, we - start)
                    if new_end <= new_start:
                        continue
                    included.append(dict(word, start=round(offset + new_start, 3),
                                         end=round(offset + new_end, 3)))
                if not included:
                    continue
                result.append({
                    "start": included[0]["start"], "end": included[-1]["end"],
                    "text": " ".join(str(w["word"]).strip() for w in included),
                    "words": included
                })
            else:
                # A truncated segment without word alignment cannot be captioned
                # accurately; omit rather than display unspoken text.
                if seg_start < start - 0.03 or seg_end > end + 0.03:
                    continue
                ns = max(0.0, seg_start - start)
                ne = min(actual_length, seg_end - start)
                if ne > ns:
                    result.append({"start": round(offset + ns, 3),
                                   "end": round(offset + ne, 3),
                                   "text": str(segment.get("text") or "").strip(),
                                   "words": [], "timing_estimated": True})
        offset += actual_length
    return sorted(result, key=lambda seg: seg["start"])


def caption_cues(segments, max_words=5, max_chars=42, max_gap=0.48):
    """Break observed speech into short cues without crossing gaps."""
    cues, current = [], []
    def flush():
        nonlocal current
        if current:
            text = " ".join(w["word"] for w in current).strip()
            if text:
                cues.append({"start": round(current[0]["start"], 3),
                             "end": round(max(current[-1]["end"], current[0]["start"] + .08), 3),
                             "text": text, "words": current})
        current = []
    for seg in segments:
        word_items = seg.get("words") or []
        if not word_items:
            flush()
            if seg.get("text") and float(seg["end"]) > float(seg["start"]):
                cues.append({"start": seg["start"], "end": seg["end"],
                             "text": seg["text"], "words": [],
                             "timing_estimated": True})
            continue
        for word in word_items:
            text = str(word.get("word") or "").strip()
            if not text:
                continue
            start, end = float(word["start"]), float(word["end"])
            if not math.isfinite(start) or not math.isfinite(end) or end <= start:
                continue
            if current and (start - current[-1]["end"] > max_gap or
                            len(current) >= max_words or
                            len(" ".join(x["word"] for x in current + [{"word": text}])) > max_chars):
                flush()
            current.append(dict(word, word=text, start=start, end=end))
            if text.endswith((".", "!", "?", "।")):
                flush()
    flush()
    return cues
