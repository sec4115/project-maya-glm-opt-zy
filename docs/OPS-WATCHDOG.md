# OPS: production-window watchdog (定时轮询规程)

Bilingual, concise. 中文在前，English mirrors it.

## 中文

任何**计划内停服或重启模型服务**的任务（生产窗口、exe 切换、引擎重启、双臂验证等），必须以**定时任务**的方式登记一个窗口 watchdog，规程如下：

1. **估计时长**：先给整个窗口估一个时长 T（分钟）。
2. **阈值 = T × 50%**：阈值取估计时长的一半（向上取整到分钟）。这是轮询的**起始等待**——正常短操作不应触发它，卡壳则远早于全额预算被发现。
3. **定时任务**（`schedule_create`，target=`this_session`）：
   - `DTSTART` = 窗口开始时刻 + 阈值（本地时区，`TZID=Asia/Shanghai`）；
   - `RRULE:FREQ=MINUTELY`（每 60 s 一次）；
   - `UNTIL` = 窗口开始 + 6 小时（安全阀，防孤儿任务）。
4. **每次触发的动作**（即任务 prompt 的内容）：访问模型服务 `/health`：
   - `status=ok` → 用 `schedule_edit`（action=`delete`）**撤销本定时任务**，然后核对窗口脚本的产出并收尾汇报；
   - 未恢复 → 在窗口目录 `poll.log` 记一行轮询结果，不做其他操作，等下一次触发；
   - 若本次触发之前**用户刚手动发消息唤醒过会话** → 同样撤销本任务（用户已接管）。
5. **手动唤醒即撤销**：窗口期间任何直接来自用户的消息（非本任务的定时投递）都会使会话撤销该 watchdog——用户在场时不需要自动轮询。
6. **报告**：窗口收尾时把阈值、轮询起止、恢复时刻写入当次窗口报告（例：`bench/results/<task-dir>/window_report.md`）。

### 本次（阶段B 窗口）的登记示例

- 窗口：停服 → 双臂批测电池（29 题 × 2 rep × 双臂）→ 报告制自动换/留 exe → 重启生产。
- 估计 T = 70 分钟 → 阈值 = 35 分钟 → `DTSTART` = 开窗 + 35 分钟，`RRULE:FREQ=MINUTELY;UNTIL=<+6h>Z`。
- 轮询目标：`http://127.0.0.1:8080/health`（生产）。

## English

For any **planned model-service outage or restart** (production window, exe swap, engine restart, two-arm battery, ...), register a window watchdog as a scheduled task:

1. **Estimate** the window duration T (minutes).
2. **Threshold = T × 50%** (round up to the minute) — the polling start delay; short normal work never triggers it, stalls surface well before the full budget.
3. **Task** (`schedule_create`, target=`this_session`): `DTSTART` = window start + threshold (`TZID` local); `RRULE:FREQ=MINUTELY` (every 60 s); `UNTIL` = window start + 6 h (orphan safety valve).
4. **Each firing** (the task prompt): GET the service `/health`:
   - `status=ok` → **delete this task** (`schedule_edit` action=`delete`), then verify the window artifacts and wrap up the report;
   - still down → append one poll line to the window dir's `poll.log`, wait for the next firing;
   - if the **user manually woke the session** since the last firing → delete the task as well (the user has taken over).
5. **Manual wake cancels**: any direct user message during the window cancels the watchdog.
6. **Report**: record the threshold, poll span, and recovery time in the window report.
