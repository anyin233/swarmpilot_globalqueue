# Scheduler 模块重构进度报告

**生成时间**: 2025-10-11
**当前阶段**: 第一阶段完成
**完成度**: ~60%

---

## ✅ 第一阶段：核心架构重构（已完成）

### 1.1 目录结构创建 ✅
```
src/scheduler/          # 核心包
├── __init__.py         # ⚠️ 需要更新导入
├── models.py           # ✅ 所有数据模型
├── task_tracker.py     # ✅ 任务跟踪器（新功能）
├── client.py           # ✅ TaskInstance 客户端
├── predictor.py        # ✅ Lookup 预测器
├── core.py             # ✅ 核心调度器
└── strategies/         # 策略子包
    ├── __init__.py     # ✅ 策略导出
    ├── base.py         # ✅ 基础类
    ├── shortest_queue.py   # ✅ 最短队列策略
    ├── round_robin.py      # ✅ 轮询策略
    ├── weighted.py         # ✅ 加权策略
    └── probabilistic.py    # ✅ 概率策略

examples/               # ⚠️ 待创建
tests/                  # ⚠️ 需要更新
docs/                   # ✅ 文档目录
```

### 1.2 核心模块创建 ✅
- ✅ **models.py** (320+ 行)
  - 所有 Pydantic 数据模型
  - Scheduler.md 规范的 API 模型
  - 兼容旧版本的模型

- ✅ **task_tracker.py** (300+ 行)
  - 线程安全的任务状态跟踪
  - 支持 queued/scheduled/completed 状态
  - 自动清理历史记录

- ✅ **client.py** (250+ 行)
  - 重构导入，使用 models.py
  - TaskInstance API 客户端

- ✅ **predictor.py** (185 行)
  - Lookup 表预测器
  - 无需修改

- ✅ **core.py** (350+ 行)
  - 集成 TaskTracker
  - 支持多种策略
  - 时间统计功能

### 1.3 策略模块拆分 ✅
- ✅ **base.py** (240 行) - 基础类和接口
- ✅ **shortest_queue.py** (350 行) - 最复杂策略，支持预测器
- ✅ **round_robin.py** (60 行) - 简单轮询
- ✅ **weighted.py** (70 行) - 加权选择
- ✅ **probabilistic.py** (140 行) - 概率选择

---

## ⏰ 第二阶段：API 和测试（待完成）

### 2.1 API 重构 - 符合 Scheduler.md 规范
**优先级**: 🔴 高

需要创建 `src/scheduler/api.py` 实现以下端点：

| 端点 | 方法 | 状态 | 说明 |
|-----|------|------|------|
| `/ti/register` | POST | ⚠️ 待实现 | 注册 Task Instance |
| `/ti/remove` | POST | ⚠️ 待实现 | 移除 Task Instance |
| `/queue/submit` | POST | ⚠️ 待实现 | 提交任务 |
| `/queue/info` | GET | ⚠️ 待实现 | 获取队列信息 |
| `/task/query` | GET | ⚠️ 待实现 | 查询任务状态 |
| `/notify/task_complete` | POST | ⚠️ 待实现 | 任务完成通知 |
| `/health` | GET | ⚠️ 待实现 | 健康检查 |

**参考**: `scheduler_api.py` (旧版本，需要调整)

### 2.2 单元测试编写
**优先级**: 🔴 高

需要创建的测试文件：

```
tests/
├── conftest.py         # pytest 配置和 fixtures
├── test_models.py      # 数据模型测试
├── test_task_tracker.py    # 任务跟踪器测试
├── test_client.py      # 客户端测试
├── test_strategies.py  # 策略测试
├── test_core.py        # 核心调度器测试
├── test_api.py         # API 端点测试
└── test_integration.py # 集成测试
```

**已有测试** (需要更新):
- `tests/test_scheduler.py` - 基础调度器测试
- `tests/test_lookup_predictor.py` - 预测器测试

### 2.3 示例代码创建
**优先级**: 🟡 中

需要在 `examples/` 目录创建：

1. **basic_usage.py** - 基本使用示例
   ```python
   # 展示如何：
   # - 初始化调度器
   # - 加载配置
   # - 提交任务
   # - 查询结果
   ```

2. **custom_strategy.py** - 自定义策略示例
   ```python
   # 展示如何：
   # - 继承 BaseStrategy
   # - 实现自定义选择逻辑
   # - 注册到调度器
   ```

3. **config_example.yaml** - 配置文件示例
   ```yaml
   instances:
     - host: localhost
       port: 8100
     - host: localhost
       port: 8101
   ```

**参考**: `example_custom_strategy.py` (旧版本)

---

## ⏰ 第三阶段：清理和文档（待完成）

### 3.1 清理旧文件
**优先级**: 🟢 低（但必须完成）

需要删除的文件：
```bash
# 旧版本文件（已被 src/ 替代）
rm api.py
rm main.py
rm strategy.py
rm task_instance_client.py
rm example_custom_strategy.py
rm scheduler.py
rm scheduler_api.py
rm strategy_refactored.py
rm task_instance_client_refactored.py
rm lookup_predictor.py

# 根目录的测试文件（已整合到 tests/）
rm test_scheduler_lookup.py
rm test_integration_lookup.py
```

**注意**: 删除前确保新代码已测试通过！

### 3.2 更新配置文件

#### pyproject.toml
需要添加：
```toml
[project]
packages = [{include = "scheduler", from = "src"}]

[project.scripts]
scheduler = "scheduler.cli:main"
```

#### cli.py
需要更新导入：
```python
# 从
from scheduler_api import app
# 改为
from src.scheduler.api import app
```

### 3.3 移动文档
将文档整理到 docs/ 目录：
```bash
mv Scheduler.md docs/
mv LOOKUP_PREDICTOR.md docs/
mv LOOKUP_PREDICTOR_TEST_REPORT.md docs/
```

### 3.4 更新 README.md
需要编写完整的项目说明：
- 项目简介
- 安装方法
- 快速开始
- API 文档链接
- 开发指南

---

## 📋 关键实现注意事项

### TaskTracker 使用
```python
# 在 core.py 中已集成
# 注册任务
self.task_tracker.register_task(
    task_id=task_id,
    ti_uuid=instance_uuid,
    model_name=model_name
)

# 标记为已调度
self.task_tracker.mark_scheduled(task_id)

# 标记为完成
self.task_tracker.mark_completed(task_id, result=result)

# 查询任务
task_info = self.task_tracker.get_task_info(task_id)
```

### API 端点实现要点

#### `/queue/submit` 实现
```python
@app.post("/queue/submit", response_model=QueueSubmitResponse)
async def submit_task(request: QueueSubmitRequest):
    # 1. 创建 SchedulerRequest
    scheduler_req = SchedulerRequest(
        model_type=request.model_name,  # 注意字段映射
        input_data=request.task_input,
        metadata=request.metadata
    )

    # 2. 调用 scheduler.schedule()
    response = scheduler.schedule(scheduler_req)

    # 3. 返回符合 Scheduler.md 的响应
    return QueueSubmitResponse(
        status="success",
        task_id=response.task_id,
        scheduled_ti=response.instance_id
    )
```

#### `/task/query` 实现
```python
@app.get("/task/query", response_model=TaskQueryResponse)
async def query_task(task_id: str):
    # 使用 TaskTracker 查询
    task_info = scheduler.task_tracker.get_task_info(task_id)

    if not task_info:
        raise HTTPException(404, "Task not found")

    return TaskQueryResponse(
        task_id=task_info.task_id,
        task_status=task_info.task_status,
        scheduled_ti=str(task_info.scheduled_ti),
        submit_time=task_info.submit_time,
        result=task_info.result
    )
```

### 测试要点

#### Mock TaskInstance 客户端
```python
@pytest.fixture
def mock_task_instance():
    mock_client = Mock(spec=TaskInstanceClient)
    mock_client.get_status.return_value = InstanceStatusResponse(
        instance_id="test-1",
        model_type="test_model",
        replicas_running=2,
        queue_size=0,
        status="running"
    )
    # ... 其他 mock 设置
    return TaskInstance(uuid=uuid4(), instance=mock_client)
```

---

## 🔧 导入路径修正

### 旧导入 → 新导入
```python
# 旧
from scheduler import SwarmPilotScheduler
from task_instance_client_refactored import TaskInstanceClient
from strategy_refactored import ShortestQueueStrategy

# 新
from src.scheduler import SwarmPilotScheduler
from src.scheduler.client import TaskInstanceClient
from src.scheduler.strategies import ShortestQueueStrategy
```

---

## 📊 当前统计

- **代码行数**: ~2500 行（新架构）
- **模块数**: 13 个核心模块
- **策略数**: 4 种调度策略
- **测试覆盖**: 0% (待编写)

---

## 🚀 下一步行动

### 立即执行（第二阶段开始）
1. 创建 `src/scheduler/api.py` - 实现所有 Scheduler.md 端点
2. 更新 `src/scheduler/__init__.py` - 添加 API 导出
3. 创建基础测试框架 - `tests/conftest.py`
4. 编写核心测试 - `tests/test_core.py`

### 详细任务清单
参见：
- `docs/PHASE2_TASKS.md` - 第二阶段详细任务
- `docs/PHASE3_TASKS.md` - 第三阶段详细任务

---

**重要提示**: 在开始第二阶段之前，建议先快速验证第一阶段的代码可以正常导入：

```bash
cd /home/yanweiye/Project/swarmpilot/swarmpilot_globalqueue
python3 -c "from src.scheduler import SwarmPilotScheduler; print('Import successful')"
```
