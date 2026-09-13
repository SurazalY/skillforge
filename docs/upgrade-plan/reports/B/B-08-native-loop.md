# B-08 补证：原生工具闭环（B-02-LOOP）

- 任务 ID：B-02-LOOP（为 B-08 §3.2 缺口提供针对性在线证据）
- 日期：2026-09-13
- 不重写 `B-08-integration.md`。完整合同、时间线、改动文件见 `docs/upgrade-plan/reports/B/B-02-native-loop.md`。

## 相对 B-08 §3.2 的缺口

B-08 系列 A 证明：首轮请求带 `tools`，`function_call` 已执行并按 `call_id` 入账。随后默认回填带 `previous_response_id` + `function_call_output` → 400 `previous_response_id is not available for this user`。**没有**最终引文句。CT07 清 `_provider_state_ref` 不能代替该闭环。

## 本次补证（默认内核路径，不是测试脚本清 state）

脚本：`D:\IDE\python\python.exe tests/b02_online_native_loop.py`  
记录：`.tmp_b02_loop_online/b02_loop_online_result.json`  
配置仍是 `codexapis.com` + `gpt-5.5` + `POST /v1/responses`。`xml_tool_compat=false`。未换供应商，未摘 `tools`。

| 步 | HTTP | tools | previous_response_id | 要点 |
|---|---|---|---|---|
| 请求工具 | 200 | 是 | 无 | `call_QLyHMtLTyRgYrVLW912Z8iC2` 执行 `read_file` notes.txt |
| 按 call_id 回填 | **200** | 是 | **无** | input：`function_call` + `function_call_output`（同一 call_id）+ user |
| 最终答复 | （同上轮响应） | — | — | `The first line is “A04-DUMMY-LINE-ONE”.`；`finish_reason=completed` |

逻辑 ask 1；HTTP 2；usage 见 B-02-native-loop.md §4。五步闭环 **PASS**。

B-08 原文把该 400 记为“交给 C 的 host 限制”。该项对**默认 ask 完成任务**不再成立：当前获准 host 的默认运行不依赖 `previous_response_id`。该字段仍是可选能力（`openai.com`），不是本 host 的必需字段。
