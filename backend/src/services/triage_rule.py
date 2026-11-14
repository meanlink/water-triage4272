"""已批准试验的规则快照与待巡管段评分。

设计约束：
- 规则快照在训练时从拟合好的决策树**确定性导出**，派单只读取快照，不重新训练，
  因此后续新增试验、批次或修改数据都不会改变已派结果。
- 旧试验结果里没有 rule_artifact 时，调用方必须向用户说明原因，禁止重训后冒充原规则。
"""
import math

RULE_ARTIFACT_VERSION = 1
# 与训练时的特征顺序严格一致，快照按索引引用特征。
FEATURES = ["night_flow", "pressure_drop", "acoustic_db", "pipe_age"]
FEATURE_LABELS = ["夜间流量(m³/h)", "压力降(kPa)", "声学读数(dB)", "管龄(年)"]


class RuleUnavailableError(ValueError):
    """旧试验缺少可复用的规则快照，且不允许重训替代。"""


def export_rule_artifact(model, params):
    """从已拟合的 DecisionTreeClassifier 导出可 JSON 序列化、可独立评分的规则快照。"""
    tree = model.tree_
    nodes = []
    for i in range(tree.node_count):
        left = int(tree.children_left[i])
        right = int(tree.children_right[i])
        is_leaf = left == -1
        counts = [float(v) for v in tree.value[i][0]]
        total = float(sum(counts))
        nodes.append({
            "id": i,
            "is_leaf": is_leaf,
            "feature_index": None if is_leaf else int(tree.feature[i]),
            "feature": None if is_leaf else FEATURES[int(tree.feature[i])],
            "threshold": None if is_leaf else float(tree.threshold[i]),
            "left": None if is_leaf else left,
            "right": None if is_leaf else right,
            "samples": int(tree.n_node_samples[i]),
            "leak_count": int(round(counts[1])),
            "total_count": int(round(total)),
            # 全精度保存，保证排序与决胜不被展示舍入影响。
            "leaf_leak_rate": (counts[1] / total) if total > 0 else 0.0,
        })
    return {
        "artifact_version": RULE_ARTIFACT_VERSION,
        "algorithm": "sklearn.tree.DecisionTreeClassifier(criterion='gini', random_state=42)",
        "features": list(FEATURES),
        "feature_labels": list(FEATURE_LABELS),
        "params": dict(params),
        "depth": int(model.get_depth()),
        "n_leaves": int(model.get_n_leaves()),
        "nodes": nodes,
        "root": 0,
    }


def _walk(nodes, node_id, values):
    path = []
    current = node_id
    guard = 0
    while not nodes[current]["is_leaf"]:
        guard += 1
        if guard > len(nodes):
            raise RuleUnavailableError("规则快照结构异常：节点路径成环，无法评分。")
        node = nodes[current]
        feature_index = node["feature_index"]
        threshold = node["threshold"]
        measured = values[feature_index]
        go_left = measured <= threshold
        path.append({
            "feature": node["feature"],
            "feature_label": FEATURE_LABELS[feature_index],
            "operator": "<=" if go_left else ">",
            "threshold": threshold,
            "measured": measured,
            "next_node": node["left"] if go_left else node["right"],
        })
        current = node["left"] if go_left else node["right"]
    return current, path


def _validate_artifact(artifact):
    if not isinstance(artifact, dict) or artifact.get("artifact_version") != RULE_ARTIFACT_VERSION:
        raise RuleUnavailableError(
            "该试验创建于规则快照功能上线前，结果中没有可复用的规则快照（缺少 rule_artifact）。"
            "为避免重训后冒充原规则，不能用它派单；请用新试验重新训练并经负责人批准后再派单。"
        )
    if artifact.get("features") != FEATURES:
        raise RuleUnavailableError("规则快照的特征口径与当前评分程序不一致，不能安全复用。")
    nodes = artifact.get("nodes")
    if not isinstance(nodes, list) or not nodes or artifact.get("root") != 0:
        raise RuleUnavailableError("规则快照缺少完整的树节点，不能派单。")
    node_ids = {n.get("id") for n in nodes}
    for n in nodes:
        if not n.get("is_leaf"):
            if n.get("left") not in node_ids or n.get("right") not in node_ids:
                raise RuleUnavailableError("规则快照节点引用不完整，不能派单。")
            if not isinstance(n.get("threshold"), (int, float)) or not (0 <= n["feature_index"] < len(FEATURES)):
                raise RuleUnavailableError("规则快照分裂条件损坏，不能派单。")
    return nodes


def score_records(artifact, records):
    """用规则快照对无标签待巡记录评分。

    返回每条记录的叶节点风险率、命中叶节点与可核对的规则路径。
    输入记录须已通过批次校验（四个特征均为非负有限数）。
    """
    nodes = _validate_artifact(artifact)
    root = artifact["root"]
    scored = []
    for row in records:
        values = [float(row[k]) for k in FEATURES]
        leaf_id, path = _walk(nodes, root, values)
        leaf = nodes[leaf_id]
        scored.append({
            "segment_id": str(row["segment_id"]),
            "features": {k: row[k] for k in FEATURES},
            "risk_rate": leaf["leaf_leak_rate"],
            "risk_pct": round(leaf["leaf_leak_rate"] * 100, 1),
            "leaf_node": leaf_id,
            "leaf_samples": leaf["samples"],
            "leaf_leak_count": leaf["leak_count"],
            "leaf_total_count": leaf["total_count"],
            "rule_path": path,
        })
    return scored


def artifact_rule_path(artifact, values):
    """按规则快照对一条特征向量返回结构化规则路径（供训练侧验证明细复用）。"""
    nodes = _validate_artifact(artifact)
    _, path = _walk(nodes, artifact["root"], list(values))
    return path


def format_rule_path(path):
    """把规则路径格式化成人类可读的单字符串，用于页面与下载核对。"""
    if not path:
        return "直接落入根叶节点（无分裂条件）"
    parts = []
    for step in path:
        parts.append(
            f"{step['feature_label']} {step['operator']} {step['threshold']:g}"
            f"（实测 {step['measured']:g}）"
        )
    return " 且 ".join(parts)


def select_dispatch(scored, quota):
    """按风险从高到低取前 quota 条；风险并列时按管段编号升序，保证结果确定。

    排序使用全精度 risk_rate，展示用的 risk_pct（1 位小数）不影响入选判定。
    """
    ranking = sorted(
        scored,
        key=lambda item: (-item["risk_rate"], item["segment_id"]),
    )
    selected_ids = {item["segment_id"] for item in ranking[:quota]}
    cutoff = ranking[quota - 1]["risk_rate"] if 0 < quota <= len(ranking) and ranking else None
    for rank, item in enumerate(ranking, start=1):
        item["rank"] = rank
        if item["segment_id"] in selected_ids:
            item["selected"] = True
            item["reason"] = (
                f"风险 {item['risk_pct']}% 排名第 {rank}，在巡检名额 {quota} 段以内"
            )
        else:
            item["selected"] = False
            if cutoff is not None and item["risk_rate"] == cutoff:
                item["reason"] = (
                    f"风险 {item['risk_pct']}% 与末位入选相同，但编号排序靠后，名额仅 {quota} 段"
                )
            else:
                item["reason"] = (
                    f"风险 {item['risk_pct']}% 排名第 {rank}，超出巡检名额 {quota} 段"
                )
    # 派单清单按管段编号升序展示，便于现场按编号核对。
    selected = sorted(
        (item for item in ranking if item["selected"]),
        key=lambda item: item["segment_id"],
    )
    return ranking, selected


def validate_patrol_records(records):
    """无标签待巡批次校验：坏行或重复编号整批拒绝，不做部分入库。"""
    if not isinstance(records, list) or not records:
        raise ValueError("待巡批次至少需要 1 条管段记录。")
    if len(records) > 5000:
        raise ValueError("单个待巡批次不能超过 5000 条记录。")
    seen = set()
    normalized = []
    for index, row in enumerate(records):
        if not isinstance(row, dict):
            raise ValueError(f"第 {index + 1} 行不是有效的记录对象，整批已拒绝。")
        sid = row.get("segment_id")
        if sid is None or str(sid).strip() == "":
            raise ValueError(f"第 {index + 1} 行缺少管段编号，整批已拒绝。")
        sid = str(sid).strip()
        if sid in seen:
            raise ValueError(f"管段编号 {sid} 在第 {index + 1} 行重复，整批已拒绝。")
        seen.add(sid)
        clean = {"segment_id": sid}
        for key, label in zip(FEATURES, FEATURE_LABELS):
            value = row.get(key)
            if value is None or value == "":
                raise ValueError(f"第 {index + 1} 行（{sid}）缺少字段 {label}，整批已拒绝。")
            if isinstance(value, bool):
                raise ValueError(f"第 {index + 1} 行（{sid}）{label} 不能是布尔值，整批已拒绝。")
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"第 {index + 1} 行（{sid}）{label} 必须是数值，整批已拒绝。")
            if not math.isfinite(number) or number < 0:
                raise ValueError(f"第 {index + 1} 行（{sid}）{label} 须为非负有限数值，整批已拒绝。")
            clean[key] = number
        normalized.append(clean)
    return normalized
