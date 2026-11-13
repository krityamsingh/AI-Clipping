"""
Lightweight content-aware edit director.

This is a transparent CPU-only transcript analysis fallback, NOT an LLM or a
semantic understanding model. It scores self-contained, coherent speech spans
using observed words and sentences. Scene/audio signals are supporting evidence,
not a substitute for story quality.
"""
import bisect
import math
import re
from collections import Counter

_STOP = set(("the a an and or but to of for on at it is are was were be been in with "
             "that this these those you your he she they we our its have has had do did "
             "does so very really just like there here from by as not what which who "
             "when how if then can could would should about yeah um uh okay ok "
             "hai hain aur mein main ki ka ke ko se par ye yeh woh wo ek hai").split())
_DANGLING = set(("and but because so then therefore also which that it he she they "
                 "aur lekin kyunki toh to isliye aur फिर लेकिन क्योंकि और तो").split())
_CLIFFHANGER = set(("and but because so if when while although or aur lekin "
                    "kyunki तो और लेकिन क्योंकि").split())


def _tokens(text):
    return re.findall(r"[^\W_]+", text.lower(), flags=re.UNICODE)


def _content_terms(text):
    return [t for t in _tokens(text) if len(t) >= 3 and t not in _STOP]


def _valid_segments(segments, duration):
    result = []
    for segment in segments:
        try:
            start = max(0.0, float(segment["start"]))
            end = min(float(duration), float(segment["end"]))
        except (KeyError, TypeError, ValueError):
            continue
        text = str(segment.get("text") or "").strip()
        if math.isfinite(start) and math.isfinite(end) and end > start and text:
            result.append(dict(segment, start=start, end=end, text=text))
    return sorted(result, key=lambda s: (s["start"], s["end"]))


class EditingDirector:
    """Ranks transcript-grounded, sentence-aligned candidate stories."""

    def rank(self, *, target_duration, num_clips, video_metadata, segments,
             audio_signals, scene_cuts):
        duration = float(video_metadata["duration"])
        if not math.isfinite(duration) or not math.isfinite(target_duration) or target_duration <= 0 or num_clips < 1:
            raise ValueError("Valid positive durations and clip count required")
        usable = _valid_segments(segments, duration)
        if not usable:
            return []

        # Generate candidate boundaries from observed speech (not arbitrary 2s windows).
        min_len = min(duration, max(4.0, target_duration * 0.62))
        max_len = min(duration, max(target_duration * 1.30, min_len))
        peaks = sorted(float(p) for p in audio_signals.get("peak_timestamps", []) if isinstance(p, (int, float)))
        cuts = sorted(float(c) for c in scene_cuts if isinstance(c, (int, float)))
        candidates = []
        seen = set()
        for i, first in enumerate(usable):
            for j in range(i, len(usable)):
                last = usable[j]
                start, end = first["start"], last["end"]
                length = end - start
                if length > max_len + 0.001:
                    break
                if length < min_len:
                    continue
                if abs(length - target_duration) > abs(max_len - target_duration) + 0.001:
                    continue
                key = (round(start, 2), round(end, 2))
                if key in seen:
                    continue
                seen.add(key)
                subset = usable[i:j + 1]
                text = " ".join(s["text"] for s in subset)
                terms = _content_terms(text)
                word_count = len(_tokens(text))
                if not word_count:
                    continue
                first_text = subset[0]["text"].strip()
                final_text = subset[-1]["text"].strip()
                first_tokens = _tokens(first_text)
                last_tokens = _tokens(final_text)
                unique = len(set(terms))
                richness = min(1.0, unique / max(5.0, len(terms) * 0.50))
                repeats = Counter(terms)
                # Coherent topics tend to recur; excessively repeated phrases
                # are penalized separately via the lexical diversity term.
                topic_recurrence = min(1.0, sum(v for v in repeats.values() if v > 1) / max(1, len(terms)))
                hook = any(c in first_text for c in "?!") or bool(re.search(r"\d", first_text))
                question_answer = "?" in first_text and j > i and "?" not in final_text
                complete_ending = final_text.endswith((".", "!", "?", "।"))
                opening_dangles = bool(first_tokens and first_tokens[0] in _DANGLING)
                ending_dangles = bool(last_tokens and last_tokens[-1] in _CLIFFHANGER)
                speech_coverage = min(1.0, sum(s["end"]-s["start"] for s in subset) / max(1.0, length))
                cut_count = bisect.bisect_left(cuts, end) - bisect.bisect_right(cuts, start)
                peak_count = bisect.bisect_left(peaks, end) - bisect.bisect_right(peaks, start)
                # A moderate speech pace helps. It is not the primary rank signal.
                wpm = word_count * 60.0 / max(length, 0.1)
                pace_score = max(0.0, 1.0 - abs(wpm - 140) / 180.0)
                score = (
                    16.0 * richness + 12.0 * topic_recurrence
                    + 19.0 * float(hook) + 7.0 * float(question_answer)
                    + 17.0 * float(complete_ending)
                    + 12.0 * speech_coverage + 10.0 * pace_score
                    + min(4.0, cut_count * 0.8) + min(3.0, peak_count * 0.3)
                    - 18.0 * float(opening_dangles) - 12.0 * float(ending_dangles)
                    - 9.0 * max(0.0, (length - target_duration) / max(target_duration, 1.0))
                )
                evidence = {
                    "opening_has_question_exclamation_or_number": bool(hook),
                    "question_followed_by_answer_candidate": bool(question_answer),
                    "ends_with_sentence_punctuation": bool(complete_ending),
                    "opening_appears_context_dependent": bool(opening_dangles),
                    "ending_appears_incomplete": bool(ending_dangles),
                    "content_terms": [term for term, _ in repeats.most_common(6)],
                    "observed_scene_cuts": cut_count,
                    "observed_audio_peaks": peak_count,
                    "speech_coverage": round(speech_coverage, 3),
                    "word_count": word_count,
                }
                candidates.append({
                    "start": round(start, 2), "end": round(end, 2),
                    "duration": round(length, 2),
                    "score": round(max(0.0, min(100.0, score)), 2),
                    "score_type": "transparent_heuristic_not_virality_probability",
                    "selection_method": "transcript_story_boundaries",
                    "evidence": evidence,
                    "text": text,
                    "speech_wpm": round(wpm, 1),
                    "cuts": cut_count, "peaks": peak_count,
                })

        candidates.sort(key=lambda x: (-x["score"], abs(x["duration"] - target_duration), x["start"]))
        selected = []
        for candidate in candidates:
            if any(candidate["start"] < old["end"] and candidate["end"] > old["start"] for old in selected):
                continue
            candidate["title"] = " ".join(candidate["text"].split()[:9]).strip(" ,;:-\"'") or "Video highlight"
            candidate["explanation"] = (
                "Transcript-aligned story candidate: " +
                ("clear ending; " if candidate["evidence"]["ends_with_sentence_punctuation"] else "ending unconfirmed; ") +
                ("strong opening; " if candidate["evidence"]["opening_has_question_exclamation_or_number"] else "ordinary opening; ") +
                f"{candidate['cuts']} observed scene cuts. Score is a heuristic, not a predicted virality rating."
            )
            selected.append(candidate)
            if len(selected) >= num_clips:
                break
        selected.sort(key=lambda item: item["start"])
        for n, item in enumerate(selected, 1):
            item["index"] = n
        return selected
