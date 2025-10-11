# 第二阶段任务清单：API 和测试

**预计时间**: 2-3小时
**优先级**: 🔴 高
**前置条件**: 第一阶段已完成

---

## 任务 2.1: 创建 API 模块 (1-1.5小时)

### 文件: `src/scheduler/api.py`

**目标**: 实现符合 Scheduler.md 规范的所有 API 端点

### 2.1.1 基础设置
```python
"""
Scheduler FastAPI Application

Implements all API endpoints defined in Scheduler.md
"""

from fastapi import FastAPI, HTTPException, Query
from loguru import logger
import os

from .core import SwarmPilotScheduler
from .models import (
    TIRegisterRequest, TIRegisterResponse,
    TIRemoveRequest, TIRemoveResponse,
    QueueSubmitRequest, QueueSubmitResponse,
    QueueInfoRequest, QueueInfoResponse, QueueInfoItem,
    TaskQueryRequest, TaskQueryResponse,
    TaskCompletionNotification
)

# Initialize scheduler
scheduler = SwarmPilotScheduler()

# FastAPI app
app = FastAPI(
    title="SwarmPilot Scheduler",
    description="Task scheduling service (v2.0 - Refactored)",
    version="2.0.0"
)
```

### 2.1.2 必须实现的端点

#### 1. `/health` - 健康检查
```python
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "scheduler", "version": "2.0.0"}
```

#### 2. `/ti/register` - 注册 Task Instance
```python
@app.post("/ti/register", response_model=TIRegisterResponse)
async def register_task_instance(request: TIRegisterRequest):
    """
    注册一个 Task Instance 到调度器

    Args:
        request: 包含 host 和 port 的注册请求

    Returns:
        注册结果，包含分配的 ti_uuid
    """
    try:
        base_url = f"http://{request.host}:{request.port}"
        ti_uuid = scheduler.add_task_instance(base_url)

        return TIRegisterResponse(
            status="success",
            message=f"TaskInstance registered successfully",
            ti_uuid=str(ti_uuid)
        )
    except Exception as e:
        logger.error(f"Failed to register TaskInstance: {e}")
        return TIRegisterResponse(
            status="error",
            message=str(e),
            ti_uuid=""
        )
```

#### 3. `/ti/remove` - 移除 Task Instance
```python
@app.post("/ti/remove", response_model=TIRemoveResponse)
async def remove_task_instance(request: TIRemoveRequest):
    """
    从调度器移除一个 Task Instance

    Args:
        request: 包含 ti_uuid 的移除请求

    Returns:
        移除结果
    """
    try:
        from uuid import UUID
        ti_uuid = UUID(request.ti_uuid)

        removed = scheduler.remove_task_instance(ti_uuid)

        if not removed:
            return TIRemoveResponse(
                status="error",
                message=f"TaskInstance {request.ti_uuid} not found",
                ti_uuid=request.ti_uuid
            )

        return TIRemoveResponse(
            status="success",
            message=f"TaskInstance removed successfully",
            ti_uuid=request.ti_uuid
        )
    except ValueError:
        return TIRemoveResponse(
            status="error",
            message="Invalid UUID format",
            ti_uuid=request.ti_uuid
        )
    except Exception as e:
        logger.error(f"Failed to remove TaskInstance: {e}")
        return TIRemoveResponse(
            status="error",
            message=str(e),
            ti_uuid=request.ti_uuid
        )
```

#### 4. `/queue/submit` - 提交任务
```python
@app.post("/queue/submit", response_model=QueueSubmitResponse)
async def submit_task(request: QueueSubmitRequest):
    """
    提交任务到调度器

    Args:
        request: 任务提交请求

    Returns:
        调度结果，包含 task_id 和 scheduled_ti
    """
    try:
        from .models import SchedulerRequest

        # 创建调度请求
        scheduler_req = SchedulerRequest(
            model_type=request.model_name,
            input_data=request.task_input,
            metadata=request.metadata
        )

        # 执行调度
        response = scheduler.schedule(scheduler_req)

        return QueueSubmitResponse(
            status="success",
            task_id=response.task_id,
            scheduled_ti=response.instance_id
        )

    except RuntimeError as e:
        logger.error(f"Scheduling failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error during scheduling: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
```

#### 5. `/queue/info` - 获取队列信息
```python
@app.get("/queue/info", response_model=QueueInfoResponse)
async def get_queue_info(model_name: Optional[str] = Query(None)):
    """
    获取所有队列的信息

    Args:
        model_name: 可选，过滤特定模型的队列

    Returns:
        队列信息列表
    """
    try:
        queues = []

        # 获取所有实例状态
        statuses = scheduler.get_instance_statuses()

        for status in statuses:
            # 如果指定了 model_name，只返回匹配的
            if model_name and status.get("model_type") != model_name:
                continue

            # 跳过错误状态的实例
            if status.get("status") == "error":
                continue

            queue_info = QueueInfoItem(
                model_name=status.get("model_type", "unknown"),
                ti_uuid=status["uuid"],
                waiting_time_expect=0.0,  # TODO: 从策略获取
                waiting_time_error=0.0    # TODO: 从策略获取
            )
            queues.append(queue_info)

        return QueueInfoResponse(
            status="success",
            queues=queues
        )

    except Exception as e:
        logger.error(f"Failed to get queue info: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

#### 6. `/task/query` - 查询任务
```python
@app.get("/task/query", response_model=TaskQueryResponse)
async def query_task(task_id: str = Query(..., description="任务ID")):
    """
    查询任务状态

    Args:
        task_id: 任务唯一标识符

    Returns:
        任务状态信息
    """
    try:
        # 从 TaskTracker 获取任务信息
        task_info = scheduler.task_tracker.get_task_info(task_id)

        if not task_info:
            raise HTTPException(
                status_code=404,
                detail=f"Task {task_id} not found"
            )

        return TaskQueryResponse(
            task_id=task_info.task_id,
            task_status=task_info.task_status,
            scheduled_ti=str(task_info.scheduled_ti),
            submit_time=task_info.submit_time,
            result=task_info.result
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to query task: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

#### 7. `/notify/task_complete` - 任务完成通知
```python
@app.post("/notify/task_complete")
async def notify_task_completion(notification: TaskCompletionNotification):
    """
    接收任务完成通知

    Args:
        notification: 任务完成通知

    Returns:
        确认响应
    """
    try:
        # 查找实例 UUID
        instance_uuid = None
        for ti in scheduler.taskinstances:
            status = ti.instance.get_status()
            if status.instance_id == notification.instance_id:
                instance_uuid = ti.uuid
                break

        if instance_uuid is None:
            logger.warning(
                f"Received completion for unknown instance: {notification.instance_id}"
            )
            return {
                "status": "warning",
                "message": f"Instance {notification.instance_id} not found"
            }

        # 处理完成
        total_time = scheduler.handle_task_completion(
            task_id=notification.task_id,
            instance_uuid=instance_uuid,
            execution_time=notification.execution_time
        )

        response = {
            "status": "success",
            "message": f"Task {notification.task_id} completion processed"
        }

        if total_time:
            response["total_time_ms"] = total_time

        return response

    except Exception as e:
        logger.error(f"Failed to process completion: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

### 2.1.3 启动事件处理
```python
@app.on_event("startup")
async def startup_event():
    """初始化调度器"""
    logger.info("Starting SwarmPilot Scheduler v2.0...")

    # 加载默认配置
    default_config = os.environ.get("SCHEDULER_CONFIG_PATH")
    if default_config and os.path.exists(default_config):
        try:
            scheduler.load_task_instances_from_config(default_config)
            logger.info(f"Loaded config from {default_config}")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8102)
```

### 2.1.4 验证清单
- [ ] 所有端点返回符合 Scheduler.md 的数据格式
- [ ] 错误处理完整（HTTPException）
- [ ] 日志记录完整
- [ ] 启动时可以加载配置文件

---

## 任务 2.2: 编写单元测试 (1-1.5小时)

### 2.2.1 创建 `tests/conftest.py`
```python
"""
Pytest 配置和共享 fixtures
"""

import pytest
from unittest.mock import Mock
from uuid import uuid4

from src.scheduler.client import TaskInstanceClient
from src.scheduler.strategies import TaskInstance
from src.scheduler.models import (
    InstanceStatusResponse,
    EnqueueResponse,
    PredictResponse
)


@pytest.fixture
def mock_task_instance():
    """创建一个 mock TaskInstance"""
    ti_uuid = uuid4()
    mock_client = Mock(spec=TaskInstanceClient)
    mock_client.base_url = "http://localhost:8100"

    # 默认状态响应
    mock_client.get_status.return_value = InstanceStatusResponse(
        instance_id="test-instance-1",
        model_type="test_model",
        replicas_running=2,
        queue_size=0,
        status="running"
    )

    # 默认预测响应
    mock_client.predict_queue.return_value = PredictResponse(
        expected_ms=100.0,
        error_ms=10.0,
        queue_size=0
    )

    # 默认入队响应
    mock_client.enqueue_task.return_value = EnqueueResponse(
        task_id="task-123",
        queue_size=1,
        enqueue_time=1234567890.0
    )

    return TaskInstance(uuid=ti_uuid, instance=mock_client)


@pytest.fixture
def scheduler_with_instances(mock_task_instance):
    """创建一个带有 mock 实例的调度器"""
    from src.scheduler import SwarmPilotScheduler

    scheduler = SwarmPilotScheduler()
    scheduler.taskinstances = [mock_task_instance]
    return scheduler
```

### 2.2.2 创建 `tests/test_task_tracker.py`
重点测试：
- 任务注册
- 状态转换
- 查询功能
- 线程安全
- 历史清理

### 2.2.3 创建 `tests/test_core.py`
重点测试：
- 调度基本流程
- 策略切换
- 实例管理（添加/移除）
- 任务完成处理
- 时间统计

### 2.2.4 创建 `tests/test_api.py`
使用 FastAPI TestClient 测试所有端点：
```python
from fastapi.testclient import TestClient
from src.scheduler.api import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_register_task_instance():
    response = client.post("/ti/register", json={
        "host": "localhost",
        "port": 8100
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "ti_uuid" in data

# ... 其他端点测试
```

### 2.2.5 运行测试
```bash
# 安装测试依赖
uv add --dev pytest pytest-asyncio pytest-cov

# 运行所有测试
uv run pytest tests/ -v

# 运行特定测试
uv run pytest tests/test_api.py -v

# 生成覆盖率报告
uv run pytest tests/ --cov=src/scheduler --cov-report=html
```

---

## 任务 2.3: 创建示例代码 (30分钟)

### 2.3.1 `examples/basic_usage.py`
```python
#!/usr/bin/env python3
"""
Basic Usage Example

Demonstrates how to use the scheduler programmatically.
"""

from src.scheduler import SwarmPilotScheduler
from src.scheduler.models import SchedulerRequest

# 1. 创建调度器
scheduler = SwarmPilotScheduler()

# 2. 加载配置
scheduler.load_task_instances_from_config("examples/config_example.yaml")

# 3. 提交任务
request = SchedulerRequest(
    model_type="test_model",
    input_data={"prompt": "Hello, world!"},
    metadata={"user": "example"}
)

response = scheduler.schedule(request)
print(f"Task {response.task_id} scheduled to {response.instance_id}")

# 4. 查询任务
task_info = scheduler.task_tracker.get_task_info(response.task_id)
print(f"Task status: {task_info.task_status}")
```

### 2.3.2 `examples/custom_strategy.py`
基于旧版 `example_custom_strategy.py` 重写

### 2.3.3 `examples/config_example.yaml`
```yaml
instances:
  - host: localhost
    port: 8100
  - host: localhost
    port: 8101
  - host: localhost
    port: 8102
```

---

## 验收标准

### API 模块
- [ ] 所有 7 个端点实现完成
- [ ] 响应格式符合 Scheduler.md
- [ ] 错误处理完整
- [ ] 可以通过 uvicorn 启动

### 测试
- [ ] 至少 4 个测试文件
- [ ] 核心功能测试覆盖 >80%
- [ ] 所有测试通过
- [ ] 无明显警告

### 示例
- [ ] 3 个示例文件创建完成
- [ ] 示例可以正常运行
- [ ] 代码有充分注释

---

## 常见问题

### Q: 如何处理导入错误？
A: 确保在项目根目录运行，并使用相对导入：
```python
from src.scheduler import SwarmPilotScheduler
```

### Q: FastAPI TestClient 如何 mock 依赖？
A: 使用 `app.dependency_overrides`：
```python
def override_scheduler():
    return mock_scheduler

app.dependency_overrides[get_scheduler] = override_scheduler
```

### Q: 测试时如何避免真实网络请求？
A: 使用 `unittest.mock` 的 `Mock` 类 mock TaskInstanceClient

---

**完成第二阶段后，继续第三阶段：清理和文档化**
