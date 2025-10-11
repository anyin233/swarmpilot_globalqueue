# 第二阶段快速开始指南

**目标**: 完成 API 实现和测试
**预计时间**: 2-3 小时

---

## 📋 前置检查

在开始之前，确认第一阶段已完成：

```bash
# 1. 检查目录结构
ls -la src/scheduler/
# 应该看到: __init__.py, core.py, models.py, task_tracker.py, client.py, predictor.py, strategies/

# 2. 检查策略模块
ls -la src/scheduler/strategies/
# 应该看到: __init__.py, base.py, shortest_queue.py, round_robin.py, weighted.py, probabilistic.py

# 3. 测试导入
python3 << 'EOF'
from src.scheduler import SwarmPilotScheduler
from src.scheduler.task_tracker import TaskTracker
from src.scheduler.strategies import ShortestQueueStrategy
print("✓ All imports successful!")
EOF
```

如果所有检查通过，继续下一步。

---

## 🎯 核心任务

### 任务 1: 创建 API 模块 (60-90分钟)

#### 步骤 1.1: 创建基础框架
```bash
# 创建 api.py 文件
touch src/scheduler/api.py
```

#### 步骤 1.2: 实现基础设置和健康检查
在 `src/scheduler/api.py` 中添加：

```python
"""Scheduler FastAPI Application"""

from fastapi import FastAPI, HTTPException, Query
from loguru import logger
import os

from .core import SwarmPilotScheduler
from .models import *  # 导入所有模型

# 初始化调度器
scheduler = SwarmPilotScheduler()

# FastAPI 应用
app = FastAPI(
    title="SwarmPilot Scheduler",
    description="Task scheduling service",
    version="2.0.0"
)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "scheduler", "version": "2.0.0"}

@app.on_event("startup")
async def startup_event():
    logger.info("Starting SwarmPilot Scheduler v2.0...")
    # 加载默认配置
    config_path = os.environ.get("SCHEDULER_CONFIG_PATH")
    if config_path and os.path.exists(config_path):
        scheduler.load_task_instances_from_config(config_path)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8102)
```

#### 步骤 1.3: 测试基础框架
```bash
# 启动服务
python3 src/scheduler/api.py

# 在另一个终端测试
curl http://localhost:8102/health

# 预期输出: {"status":"healthy",...}
# Ctrl+C 停止服务
```

#### 步骤 1.4: 实现剩余端点
依次实现以下端点（参考 PHASE2_TASKS.md 的详细代码）：

1. ✅ `/health` (已完成)
2. ⏰ `/ti/register` - 注册 Task Instance
3. ⏰ `/ti/remove` - 移除 Task Instance
4. ⏰ `/queue/submit` - 提交任务
5. ⏰ `/queue/info` - 获取队列信息
6. ⏰ `/task/query` - 查询任务
7. ⏰ `/notify/task_complete` - 任务完成通知

**提示**: 每实现一个端点，立即使用 curl 测试！

---

### 任务 2: 编写测试 (60-90分钟)

#### 步骤 2.1: 创建测试配置
```bash
# 创建 conftest.py
cat > tests/conftest.py << 'EOF'
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
    ti_uuid = uuid4()
    mock_client = Mock(spec=TaskInstanceClient)
    mock_client.base_url = "http://localhost:8100"

    mock_client.get_status.return_value = InstanceStatusResponse(
        instance_id="test-1",
        model_type="test_model",
        replicas_running=2,
        queue_size=0,
        status="running"
    )

    mock_client.predict_queue.return_value = PredictResponse(
        expected_ms=100.0,
        error_ms=10.0,
        queue_size=0
    )

    mock_client.enqueue_task.return_value = EnqueueResponse(
        task_id="task-123",
        queue_size=1,
        enqueue_time=1234567890.0
    )

    return TaskInstance(uuid=ti_uuid, instance=mock_client)

@pytest.fixture
def scheduler_with_instances(mock_task_instance):
    from src.scheduler import SwarmPilotScheduler
    scheduler = SwarmPilotScheduler()
    scheduler.taskinstances = [mock_task_instance]
    return scheduler
EOF
```

#### 步骤 2.2: 创建 TaskTracker 测试
```bash
cat > tests/test_task_tracker.py << 'EOF'
import pytest
from uuid import uuid4
from src.scheduler.task_tracker import TaskTracker
from src.scheduler.models import TaskStatus

def test_register_task():
    tracker = TaskTracker()
    ti_uuid = uuid4()

    tracker.register_task(
        task_id="task-1",
        ti_uuid=ti_uuid,
        model_name="test_model"
    )

    task_info = tracker.get_task_info("task-1")
    assert task_info is not None
    assert task_info.task_id == "task-1"
    assert task_info.task_status == TaskStatus.QUEUED

def test_mark_scheduled():
    tracker = TaskTracker()
    ti_uuid = uuid4()

    tracker.register_task("task-1", ti_uuid, "test_model")
    tracker.mark_scheduled("task-1")

    task_info = tracker.get_task_info("task-1")
    assert task_info.task_status == TaskStatus.SCHEDULED

def test_mark_completed():
    tracker = TaskTracker()
    ti_uuid = uuid4()

    tracker.register_task("task-1", ti_uuid, "test_model")
    tracker.mark_completed("task-1", result={"output": "test"})

    task_info = tracker.get_task_info("task-1")
    assert task_info.task_status == TaskStatus.COMPLETED
    assert task_info.result == {"output": "test"}

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
EOF
```

#### 步骤 2.3: 创建 Core 测试
```bash
cat > tests/test_core.py << 'EOF'
import pytest
from src.scheduler.models import SchedulerRequest

def test_schedule_success(scheduler_with_instances):
    request = SchedulerRequest(
        model_type="test_model",
        input_data={"prompt": "test"},
        metadata={}
    )

    response = scheduler_with_instances.schedule(request)

    assert response.task_id == "task-123"
    assert response.model_type == "test_model"

def test_schedule_no_instances():
    from src.scheduler import SwarmPilotScheduler
    scheduler = SwarmPilotScheduler()

    request = SchedulerRequest(
        model_type="test_model",
        input_data={"prompt": "test"},
        metadata={}
    )

    with pytest.raises(RuntimeError, match="No TaskInstances configured"):
        scheduler.schedule(request)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
EOF
```

#### 步骤 2.4: 创建 API 测试
```bash
cat > tests/test_api.py << 'EOF'
from fastapi.testclient import TestClient

def test_health_check():
    from src.scheduler.api import app
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

# TODO: 添加更多 API 测试

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
EOF
```

#### 步骤 2.5: 运行测试
```bash
# 运行所有测试
uv run pytest tests/ -v

# 应该看到所有测试通过
```

---

### 任务 3: 创建示例 (20-30分钟)

#### 步骤 3.1: 创建配置示例
```bash
cat > examples/config_example.yaml << 'EOF'
instances:
  - host: localhost
    port: 8100
  - host: localhost
    port: 8101
EOF
```

#### 步骤 3.2: 创建基本使用示例
```bash
cat > examples/basic_usage.py << 'EOF'
#!/usr/bin/env python3
"""Basic Usage Example"""

from src.scheduler import SwarmPilotScheduler
from src.scheduler.models import SchedulerRequest

# 1. 创建调度器
scheduler = SwarmPilotScheduler()

# 2. 加载配置
scheduler.load_task_instances_from_config("examples/config_example.yaml")

print(f"Loaded {len(scheduler.taskinstances)} TaskInstances")

# 3. 提交任务
request = SchedulerRequest(
    model_type="test_model",
    input_data={"prompt": "Hello, world!"},
    metadata={"user": "example"}
)

try:
    response = scheduler.schedule(request)
    print(f"✓ Task {response.task_id} scheduled to {response.instance_id}")

    # 4. 查询任务
    task_info = scheduler.task_tracker.get_task_info(response.task_id)
    print(f"✓ Task status: {task_info.task_status}")

except Exception as e:
    print(f"✗ Error: {e}")
EOF

chmod +x examples/basic_usage.py
```

---

## ✅ 验收清单

完成后，检查以下项目：

### API 实现
- [ ] 7 个端点全部实现
- [ ] 每个端点都能正常响应
- [ ] 错误处理完整
- [ ] 日志输出清晰

### 测试
- [ ] `conftest.py` 创建完成
- [ ] `test_task_tracker.py` 至少 3 个测试
- [ ] `test_core.py` 至少 2 个测试
- [ ] `test_api.py` 至少 1 个测试
- [ ] 所有测试通过

### 示例
- [ ] `config_example.yaml` 创建
- [ ] `basic_usage.py` 可运行
- [ ] 代码有注释

---

## 🐛 常见问题

### Q: 导入错误 "No module named 'src'"
**A**: 确保在项目根目录运行命令，并且 Python 路径正确：
```bash
cd /home/yanweiye/Project/swarmpilot/swarmpilot_globalqueue
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### Q: 测试中 Mock 对象行为不正确
**A**: 检查 Mock 的返回值设置：
```python
mock_client.get_status.return_value = ...  # 正确
mock_client.get_status = ...  # 错误
```

### Q: API 启动报错 "Port already in use"
**A**: 更换端口或关闭占用端口的进程：
```bash
# 查找占用进程
lsof -i :8102

# 更换端口
uvicorn src.scheduler.api:app --port 8103
```

---

## 📚 参考资料

- 详细任务说明: `docs/PHASE2_TASKS.md`
- 第一阶段成果: `docs/REFACTORING_PROGRESS.md`
- API 规范: `docs/Scheduler.md`

---

## 🎉 完成后

完成所有任务后：

1. **提交代码**
   ```bash
   git add src/scheduler/api.py tests/ examples/
   git commit -m "feat: complete Phase 2 - API and tests"
   ```

2. **准备第三阶段**
   - 查看 `docs/PHASE3_TASKS.md`
   - 确保所有测试通过
   - 备份当前状态

3. **休息一下** ☕
   恭喜！你已经完成了最困难的部分！

---

**下一步**: 第三阶段 - 清理和文档化 (见 `docs/PHASE3_TASKS.md`)
