# Тесты F4/M3.1 в модуле коуча: нормативный темп сегментов от LTSP,
# потолок пульса карточки от LTHR, numeric_check с LTHR-лестницей.
# (Coach-side F4/M3.1: threshold-pace segment hints, LTHR-anchored card ceilings,
# prose numeric check against the LTHR ladder.)

from src.coach.contracts import Prescription, SafetyVerdict, WorkoutSegment
from src.coach.numeric_check import check_prose
from src.coach.render import render_prescription, render_prescription_short
from src.coach.segments import enrich_and_clamp_segments


def _seg(**kw) -> WorkoutSegment:
    base = dict(role="steady", amount_kind="min", amount_value=30, target_zone=2)
    base.update(kw)
    return WorkoutSegment(**base)


def _enrich(segments, *, ltsp=None, lthr=None, db=None, wtype="interval"):
    return enrich_and_clamp_segments(
        segments, workout_type=wtype, proposal_type=wtype,
        max_zone=5, max_hr=180, user_id=1, db=db, lthr=lthr, ltsp_s_km=ltsp)


# --- segments: нормативная ступень темпа от порогового темпа (LTSP) ---

class TestSegmentsThresholdPace:
    def test_z4_pace_hint_from_ltsp(self):
        """Нет истории (db=None), есть LTSP=321 с/км → Z4: (321-17)/60 = 5.07."""
        out = _enrich([_seg(role="work", target_zone=4)], ltsp=321.0)
        assert out[0]["pace_hint_min_km"] == 5.07
        assert out[0]["pace_source"] == "threshold"
        assert out[0]["pace_missing"] is False

    def test_z2_pace_hint_from_ltsp(self):
        """Z2: (321+75)/60 = 6.6 — ступень «плюс к порогу» для лёгких зон."""
        out = _enrich([_seg(target_zone=2)], ltsp=321.0, wtype="easy")
        assert out[0]["pace_hint_min_km"] == 6.6
        assert out[0]["pace_source"] == "threshold"

    def test_without_ltsp_pace_missing(self):
        """Ни истории, ни LTSP → честная пометка «мало данных»."""
        out = _enrich([_seg(role="work", target_zone=4)])
        assert out[0]["pace_hint_min_km"] is None
        assert out[0]["pace_missing"] is True
        assert out[0]["pace_source"] is None

    def test_history_wins_over_threshold(self, monkeypatch):
        """Личная история приоритетнее нормативной ступени (source='history')."""
        import src.services.workout_insights as wi
        monkeypatch.setattr(wi, "expected_pace_at_hr",
                            lambda uid, hr, *, db: {"pace_min_km": 6.5, "n_points": 9})
        out = _enrich([_seg(target_zone=2)], ltsp=321.0, db=object(), wtype="easy")
        assert out[0]["pace_hint_min_km"] == 6.5
        assert out[0]["pace_source"] == "history"

    def test_hr_ceiling_uses_lthr_ladder(self):
        """Потолок пульса сегмента от LTHR: Z2 → floor(156·0.89) = 138 (vs 144)."""
        out = _enrich([_seg(target_zone=2)], lthr=156, wtype="easy")
        assert out[0]["hr_ceiling"] == 138
        out_fb = _enrich([_seg(target_zone=2)], wtype="easy")
        assert out_fb[0]["hr_ceiling"] == 144


# --- render: потолок зоны в карточке от LTHR ---

def _hr_lead_prescription():
    return Prescription(safety=SafetyVerdict(), workout_type="easy",
                        target={"max_zone": 2}, volume={"duration_min": 40})


class TestRenderLthr:
    def test_card_ceiling_from_lthr(self):
        """Карточка HR-режима: с LTHR=156 → «пульс до 138», без → «до 144»."""
        p = _hr_lead_prescription()
        assert "пульс до 138" in render_prescription(p, max_hr=180, lthr=156)
        assert "пульс до 144" in render_prescription(p, max_hr=180)

    def test_short_line_ceiling_from_lthr(self):
        """Короткая строка-напоминание тоже считает потолок от LTHR."""
        p = _hr_lead_prescription()
        assert "пульс до 138" in render_prescription_short(p, max_hr=180, lthr=156)
        assert "пульс до 144" in render_prescription_short(p, max_hr=180)


# --- numeric_check: эталон пульса от LTHR-лестницы ---

class TestNumericCheckLthr:
    def test_lthr_ceiling_not_flagged(self):
        """Проза называет потолок LTHR-лестницы (138) — с lthr это не mismatch,
        а против fallback-эталона (144) — расхождение (|138-144| > 5)."""
        p = _hr_lead_prescription()
        msg = "Сегодня легко: держи пульс до 138 уд/мин."
        assert check_prose(msg, p, max_hr=180, lthr=156) == []
        assert check_prose(msg, p, max_hr=180) != []

    def test_fallback_ceiling_flagged_when_lthr_active(self):
        """Обратный кейс: проза с fallback-числом 144 при активном LTHR — mismatch."""
        p = _hr_lead_prescription()
        msg = "Держи пульс до 144 уд/мин."
        assert check_prose(msg, p, max_hr=180, lthr=156) != []
