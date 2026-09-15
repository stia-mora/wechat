"""Evidence-based, versioned account scoring."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

VERSION = "2026-09-evidence-v2"
DIMENSIONS = ("论证深度", "来源透明度", "信息增量", "表达清晰度", "观点审慎性")
RUBRIC = """固定评价五项：论证深度（解释机制、因果与替代解释）；来源透明度（可识别出处、数据口径、引用）；
信息增量（样本中具体数据、案例或分析，不能据此断言全网原创）；表达清晰度（结构、术语解释、结论一致性）；
观点审慎性（事实与观点区分、适用边界、反面证据）。
各项统一分档：0=有充分证据显示严重缺陷；1=明显薄弱；2=基础但存在具体缺口；3=合格且有可核查支撑；
4=多个样本持续表现优秀、说明不足；5=至少三个不同样本表现突出且明确检验局限，极少使用。
分数使用0.5步长。不要根据账号名气、官方身份、文章篇幅或文风给高分，不要求拉开差距或强制分布。
每项解释评分理由和限制，给出输入中的article_id及逐字短引文（不能改写），至少两篇不同文章支持才评分，5分至少三篇。
证据不足score=null并解释原因，不当作0分。不能仅凭文本评价事实准确性、全网原创性、互动效果或权威性。
评分只反映给定样本，不能声称事实核查完成。"""


class Evidence(BaseModel):
    article_id: int
    quote: str = Field(min_length=4, max_length=180)


class Assessment(BaseModel):
    dimension: Literal["论证深度", "来源透明度", "信息增量", "表达清晰度", "观点审慎性"]
    score: float | None = Field(ge=0, le=5, multiple_of=0.5)
    reason: str = Field(min_length=8)
    limitation: str = Field(min_length=4)
    evidence: list[Evidence] = Field(max_length=5)

    @model_validator(mode="after")
    def enough_evidence(self):
        if self.score is not None and len({e.article_id for e in self.evidence}) < (
            3 if self.score == 5 else 2
        ):
            raise ValueError("评分至少需要两篇文章证据，5分至少三篇")
        return self


def finalize(data, articles, strict=True):
    samples = {a["id"]: a["content_text"][:6000] for a in articles}
    for item in data["assessments"]:
        valid = []
        for evidence in item["evidence"]:
            if (
                evidence["article_id"] not in samples
                or evidence["quote"] not in samples[evidence["article_id"]]
            ):
                if strict:
                    raise ValueError(f"文章 {evidence['article_id']} 的引文不匹配：{evidence['quote']}。必须选择该文章中连续的逐字原文，不能改写或省略")
            else:
                valid.append(evidence)
        if len(valid) != len(item['evidence']):
            item['evidence'] = valid
            item['score'] = None
            item['reason'] = '部分引用未通过原文校验，无法可靠判断本项表现。'
            item['limitation'] = '已移除不匹配的引用，需重新分析或人工审核。'
    data["scoring_version"] = VERSION
    data["quality_scores"] = {a["dimension"]: a["score"] for a in data["assessments"]}
    scores = list(data["quality_scores"].values())
    # Unknown dimensions and small samples must not inflate an average.
    data["overall_score"] = (
        round(sum(scores) * 4, 1)
        if len(articles) >= 20 and all(s is not None for s in scores)
        else None
    )
    data["sample_article_ids"] = list(samples)
    data["sample_policy"] = "最近20篇可读正文，每篇最多前6000字；不足20篇不生成综合分"
    return data
