from competitive_intel.domain.analytical_writing import validate_document

def fixture_payload(packet):
    ids = list(packet["facts"])
    units = []
    texts = ["共同能力名称只适合作为比较起点，需要继续区分各自处理的工作环节。",
             "功能描述之间的差异需要放回任务流程中理解，不能直接转化为效果差距。",
             "现有材料可以限定比较问题，但尚不能支持实际效果与整体价值的排名。",
             "建议围绕同一业务任务建立对照试点，再决定是否扩大部署范围。"]
    for section, text in zip(["overview", "differences", "conclusions", "recommendations"], texts):
        units.append(dict(section=section, kind="recommendation" if section == "recommendations" else "inference",
            text=text, fact_ids=ids, finding_ids=[], premise="以当前已收集的功能说明为比较范围，不假设实际效果。",
            verification="记录任务完成情况、人工介入步骤与失败原因。" if section == "recommendations" else ""))
    return {"units": units}


def reviewed(payload, packet):
    # Explicit synthetic fixture oracle; not a runtime semantic reviewer.
    _, diagnostics = validate_document(payload, packet)
    assert all(d["code"] == "SEMANTIC_REVIEW_REQUIRED" for d in diagnostics)
    return {d["fingerprint"]: "Fixture reviewer: conditional experimental advice; no claimed product effects." for d in diagnostics}


