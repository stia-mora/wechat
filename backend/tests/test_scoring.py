import copy

import pytest

from app.scoring import DIMENSIONS, Assessment, finalize


def sample():
    articles = [{"id": i, "content_text": "可核查的样本原文"} for i in range(20)]
    data = {
        "assessments": [
            {
                "dimension": d,
                "score": 3,
                "reason": "样本提供明确可解释的证据",
                "limitation": "没有外部事实核查",
                "evidence": [{"article_id": i, "quote": "样本原文"} for i in (0, 1)],
            }
            for d in DIMENSIONS
        ]
    }
    return data, articles


def test_evidence_and_unknown_scores():
    data, articles = sample()
    assert finalize(copy.deepcopy(data), articles)["overall_score"] == 60
    assert finalize(copy.deepcopy(data), articles[:3])["overall_score"] is None
    data["assessments"][0]["score"] = None
    assert finalize(copy.deepcopy(data), articles)["overall_score"] is None
    data["assessments"][0]["evidence"][0]["quote"] = "不存在的原文"
    with pytest.raises(ValueError):
        finalize(data, articles)
    safe = finalize(data, articles, strict=False)
    assert safe['overall_score'] is None
    assert safe['assessments'][0]['score'] is None
    assert all(e['quote'] != '不存在的原文' for e in safe['assessments'][0]['evidence'])


def test_high_score_needs_three_distinct_articles():
    data, _ = sample()
    entry = data["assessments"][0]
    entry["score"] = 5
    with pytest.raises(ValueError):
        Assessment.model_validate(entry)
    entry["evidence"].append({"article_id": 2, "quote": "样本原文"})
    assert Assessment.model_validate(entry).score == 5
