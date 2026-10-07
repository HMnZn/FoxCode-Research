# Memory：有来源、版本和有效期的项目记忆

## 1. 为什么不是把历史对话塞进向量库

历史对话包含临时错误、被替换的命令、过时的文件位置和模型猜测。即使语义检索很强，也可能把一个“很像问题但已经错了”的事实召回。

所以 Memory 的质量问题至少分为写入、证据、时间有效性、项目隔离和检索。相似度只解决其中一部分。

[MemGPT](https://arxiv.org/abs/2310.08560) 讨论了分层 memory 和有限上下文之间的数据移动。本项目借鉴问题划分，实际实现采用 SQLite/FTS5 和确定性策略，没有复现其模型控制的中断与存储管理。

## 2. 三类信息不要混用

| 类型 | 例子 | 存放位置 |
| --- | --- | --- |
| Working | 当前目标、刚读过的文件、未解决失败 | `TaskState`，随当前 Agent 会话变化 |
| Episodic | 一次 parser 修复经过、失败、修改和检查输出 | Memory 数据库，关联 trajectory ID |
| Semantic | 项目采用什么检查命令、明确的用户偏好 | Memory 数据库，可带事实 key 和支持证据 |

Memory 记录事实和经验；Skill 记录复用方法；Context 决定本次模型究竟看到它们中的哪些。

## 3. 数据模型从内容升级成知识记录

源码：[store.py](../../packages/fox_coding_agent/src/memory/store.py)。

每条 Memory 保存内容、类型、scope、source、confidence、success、verify，以及：

| 字段 | 作用 |
| --- | --- |
| `fingerprint` | 规范化空白后计算内容 hash，用于完全重复内容去重 |
| `key` | 同一个项目事实的稳定身份，比如 `test-command` |
| `status` | active / provisional / superseded / invalidated |
| `version`、`supersedes` | 知识修订与前一版本的链接 |
| `updated_at`、`expires_at` | 最近更新和有效期 |
| `metadata` | 结构化任务信息、证据计数、验证时间、文件指纹 |

另有 `memory_evidence` 表，按 `(memory_id, source, kind)` 唯一约束去重。文本内容和证据分开：同一句事实可以被不同轨迹支持；同一轨迹重复写十次仍不是十份独立证据。

`memory_fts` 中存搜索词，`memories` 中存原始内容；读取时通过 rowid 关联。FTS 是候选搜索索引，不承担事实真值判断。

已有旧数据库通过添加字段升级，旧记录保留；新字段不会要求删除原来的 `.foxcode/research`。

## 4. 写入策略：哪些东西可以自动沉淀

### Episodic：保存执行经历

`CodingAgent._save_experience()` 从本次轨迹生成 Episode：任务、结束状态、修改、测试观测、失败、工具次数和变更文件指纹。

数据来自本次 `trajectory.tools`，不是从可能累积了多个用户回合的 `TaskState.changes` 拿数据。这样第二次任务只读文件时，不会误称又执行了一次之前的写入。

`completed` 是模型循环正常结束的状态，不能直接转换成“任务正确”。Episode 保留具体观测，供以后解释和外部评估。

`learn=False` 的执行保留原始轨迹但不新增 Episode/项目事实；显式 Skill trial 默认采用这个模式，防止验证轨迹回流到下一次 Memory 检索。普通学习任务默认写入。

### Semantic：明确事实或有证据的观察

用户通过 `/api/memory` 明确添加的事实可以直接 active，但 `verify=True` 时仍以需要检查的历史线索注入。

自动事实采用窄规则：成功执行已识别的检查命令，且输出没有明显失败标记时，保存“观察到该命令在项目中成功执行”的事实。它不意味着完整任务通过全部测试，也不意味着任意 shell 命令可自动变成事实。

首次观察写 provisional；至少两个不同 trajectory source 的工具观察才 active：

```text
同一轨迹 t1 多次成功 -> support=1，仍 provisional
另一轨迹 t2 也观察成功 -> support=2，active
```

置信度采用可见的启发式 `min(0.95, 0.5 + 0.15 * support)`，默认有效期为 30 天。它不是校准过的概率，也没有自动概括任意模型文本。

不同 trajectory ID 只保证来源 ID 不重复，不能保证任务在统计上独立。数据集划分和语义去重需要外部评估侧处理。

## 5. 冲突处理：新事实如何替代旧事实

设同一个项目事实 key 为 `test-command`：

```text
v1: 项目使用 pytest
v2: 项目改用 unittest
```

写入 v2 时，v1 标记 superseded，v2 记录 `supersedes=v1.id`。查询默认排除 superseded，旧记录仍可按 ID 查询。

这是“有稳定 key 的显式事实修订”，不是自然语言矛盾检测。没有 key 的两段文字即使互相矛盾，也不会自动被模型判断哪条正确。新自动事实在 evidence 未达门槛前仍可能 provisional，此时不能把它当作稳定知识召回。

对已经确认不适用的记录，可调用 `invalidate(id, reason)`；API 为 `POST /api/memory/invalidate`。失效理由留在 metadata，不直接删除证据。

## 6. 时间有效性与文件有效性不同

### TTL

查询前过滤：

```text
status == active
AND (expires_at is NULL OR expires_at > now)
```

超时事实不参与召回，但仍保留用于审计。无 TTL 的偏好不会因为日期变化自动失效。面板的 counts 是 active/provisional 存储条数，不代表全部仍处于 TTL 内。

### 文件指纹

`fingerprint_files()` 对关联文件记录 SHA-256。查询传入 cwd 时重新比较：

```text
当前 hash != 记录 hash，或文件消失
  -> stale_paths
  -> stale=-0.6
  -> prompt 明确提醒关联文件已变化
```

当前只对存在且大小不超过 1 MB 的文件做指纹。默认自动 Episode 关联本次成功 Write/Edit 的文件。自动命令事实还没有完整依赖闭包；可通过 `observe_fact(..., metadata={file_fingerprints: ...})` 提供实验侧的依赖文件集合。

文件变化只表示证据环境变了，不一定表示事实错误，所以保留为历史线索并降权，不直接宣布记忆为假。实际内容依然需要 Agent 使用 Read/Glob/Bash 核验。

## 7. 检索分成四步

源码：[retrieval.py](../../packages/fox_coding_agent/src/memory/retrieval.py)。

```mermaid
flowchart LR
    Q[当前任务 query] --> G[项目 / global 范围与有效性过滤]
    G --> B[FTS5 BM25 候选，最多 40 条]
    B --> R[可解释 rerank]
    R --> D[MMR 风格多样性选择]
    D --> C[Context 按 token 预算决定实际注入]
```

### 第一阶段：项目与状态过滤

仅检索当前 scope 或 global。当前 scope 是规范化项目绝对路径；默认数据库也位于该项目目录。其他项目内容不靠“分数较低”隔离，而是 SQL 条件过滤。

### 第二阶段：BM25 候选搜索

英文按单词、中英文路径中的英文字段按 token、中文连续文本按双字片段处理。最多使用 query 的前 40 个去重词。

FTS5 返回 BM25 rank，代码把候选集合中的绝对值归一化。它适合文件名、命令、错误类型等词面匹配；同义词和抽象概念的召回是限制。未引入向量库，也未实现 embedding 搜索。

### 第三阶段：可解释 rerank

```text
score = normalized_bm25
      + 0.2 * 2^(-age / half_life)
      + 0.2 * same_project
      + 0.2 * confidence
      + 0.1 * success
      + 0.3 * query_coverage
      + 0.1 * independently_supported
      - 0.6 * stale_file_evidence
```

Semantic half-life=90 天；Episodic=14 天。两类信息的时效不同：某一次具体任务经验可以快速降权，稳定项目知识降权慢一些。

`query_coverage` 是 query token 在内容中命中的比例。所有分量通过 `breakdown` 返回。这些权重均为研究起点，没有经过学习或效果调参。

### 第四阶段：多样性

若 top-3 都是近乎重复的 pytest 记录，很少增加信息。选择时使用：

```text
selection_score = score - 0.65 * max Jaccard(content_tokens, selected_tokens)
```

每选一条，就重新计算剩余候选与已选集合的最大相似度。这是 MMR 风格的相关性/冗余权衡，不是 embedding MMR 的复现。候选上限 40，top-k 默认 3，计算量适合项目级研究。

最后 Context 还会按输入额度决定是否真的放入 prompt。Memory 检索评分没有等同于模型实际使用情况。

## 8. 一个可以单独运行的例子

```python
from tempfile import TemporaryDirectory
from pathlib import Path
from fox_coding_agent.src.memory import MemoryStore, retrieve

with TemporaryDirectory() as directory:
    store = MemoryStore(Path(directory) / "memory.sqlite")
    fact = store.observe_fact("check", "Run pytest parser", scope="demo", source="task-1")
    assert retrieve(store, "parser", "demo") == []  # 还在 provisional
    store.observe_fact("check", "Run pytest parser", scope="demo", source="task-2")
    hit = retrieve(store, "parser", "demo")[0]
    print(hit["breakdown"], hit["memory"]["metadata"])
    store.invalidate(fact, "project switched test framework")
    assert retrieve(store, "parser", "demo") == []
    store.close()
```

这演示了机制，不构造成功率或节省 token 的结论。

## 9. 如何读源码与定位问题

1. 看 `Memory` dataclass：内容之外的信息有哪些。
2. 看 `add()`：完全重复去重和带 key 的修订。
3. 看 `observe_fact()`：支持证据如何去重，什么时候 active。
4. 看 `retrieve()`：过滤、BM25、rerank、多样性。
5. 看 `format_memories()`：source/version/stale 如何进入模型输入。
6. 看 `CodingAgent._save_experience()`：真实工具轨迹怎么产生记忆。

```bash
uv run python -m pytest tests/test_research_policies.py -q -k memory
```

如果召回结果不理想，先看 scope、status、expires_at，再看 FTS 是否词面命中，最后看 breakdown 和 diversity_penalty。不要一开始就把问题归结为“需要 embedding”。

## 10. 面试追问

**为什么选 SQLite，而不是向量数据库？** 文件、命令和异常检索适合词面检索；项目规模较小，需要可解释、低依赖。向量检索应先证明当前的词面召回不足，再作为对照变量加入。

**记忆怎么防止幻觉？** 对写入源做区分，模型解释不直接晋升为项目事实；保留工具来源、支持数、版本和有效性。只能降低风险，不能保证每条记忆真且当前适用。

**相同事实出现多次就更可信？** 同一 source 重复不会增加独立支持；不同 source 也不自动等于统计独立，所以置信度只是启发式。

**新旧知识冲突怎么办？** 对同 scope/key 的事实做版本替代；没有 key 的自然语言矛盾暂时交给显式纠正与人工失效接口，不声称完成了知识图谱推理。

**为什么检索后还可能丢弃？** 召回解决相关性，Context 解决信息预算，模型是否采用又是另一件事。三个阶段分别记日志才能解释问题。

## 11. 后续评估设计，当前未运行

建议外部定义：事实正确率、stale 事实引用率、跨项目泄漏率、召回覆盖、重复召回比例、使用前核验比例，以及终端任务判分。比较无 Memory、BM25-only、增加有效性治理、增加 rerank、增加多样性。

潜在扩展包括 RRF 融合词面与语义候选、事件级事实修订、带依赖图的失效传播。收益数据应来自冻结任务集，避免把训练/沉淀来源直接当测试集。
